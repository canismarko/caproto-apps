from contextlib import contextmanager
import contextvars
import functools

from caproto.server import pvproperty, PvpropertyDouble
from caproto._data import SkipWrite
from caproto.server.records import MotorFields, register_record
from caproto.asyncio.client import Context
import warnings



class ReentryManager():
    _states: dict = {}

    def __call__(self, func):
        """

        Parameters
        ==========
        func
          The callable to enter.
        """
        @functools.wraps(func)
        async def inner(*args, **kwargs):
            
            # Get the current state for this call
            obj = args[0]
            var_name = f"{id(obj)}-{id(func)}"
            is_running = self._states.setdefault(var_name, False)
            if is_running:
                return
            try:
                self._states[var_name] = True
                return await func(*args, **kwargs)
            finally:
                self._states[var_name] = False

        return inner

    @contextmanager
    def block(self, *targets, obj):
        """Context manager that prevents secondary functions for running."""
        var_names = [f"{id(obj)}-{id(target)}" for target in targets]
        old_states = {}
        for var_name in var_names:
            old_states[var_name] = self._states.get(var_name, False)
            self._states[var_name] = True
        # Execute the wrapped code
        try:
            yield
        finally:
            # Restore original states
            for var_name in var_names:
                self._states[var_name] = old_states[var_name]
            

no_reentry = ReentryManager()


@register_record
class MotorFieldsBase(MotorFields):
    parent_context: Context
    _record_type = "motor_base"

    # Over-ridden PVs
    motor_step_size = pvproperty(
        name="MRES", dtype=PvpropertyDouble, doc="Motor Step Size (EGU)", value=1.,
    )

    def __init__(self, *args, axis_num: int = 99, **kwargs):
        self.axis_num = axis_num
        super().__init__(*args, **kwargs)
        self.parent_context = None
        self.parent_pv = None
        self.parent_subscription = None

    @MotorFields.description.startup
    async def description(self, instance, async_lib):
        # Save the async lib for later use
        self.async_lib = async_lib
        # Set the fields to the PV spec properties
        doc_string = self.parent.__doc__
        if doc_string is not None:
            await instance.write(doc_string)

    @MotorFields.dial_desired_value.startup
    async def dial_desired_value(self, instance, async_lib):
        # Look for new values coming from the parent class
        self.parent_context = Context()
        (self.parent_pv,) = await self.parent_context.get_pvs(self.parent.pvname)
        self.parent_subscription = self.parent_pv.subscribe()
        self.parent_subscription.add_callback(self.handle_new_user_desired_value)

    @no_reentry
    async def handle_new_user_desired_value(self, pv, response):
        """Handle changes to the user setpoint value.

        This needs to be a callback on client subscription, since the
        .VAL field resides on the parent pvproperty and not on this
        record object itself.

        """
        user_setpoint = response.data[0]
        ignore_set = bool(self.ignore_set_field.value)
        if self.set_use_switch.value in [1, "Set"] and not ignore_set:
            # Update the calibration offset
            await self.user_offset.write(self._user_to_offset(user_setpoint))
            await self.update_user_values()
        else:
            # Update the dial set point
            try:
                await self.check_limits(user_setpoint, which="user")
            except SkipWrite:
                pass
            await self.dial_desired_value.write(self._user_to_dial_value(user_setpoint))

    async def update_user_values(
        self,
        setpoint: float = None,
        readback: float = None,
        high_limit: float = None,
        low_limit: float = None,
        offset: float = None,
        direction: float = None,
    ):
        """Update the user values based on dial values.

        The various parameters should be the corresponding dial
        values. If omitted, the current values will be used. If
        ``False`` the corresponding user value will not be updated.

        """
        # Get current values if not provided as arguments
        setpoint = self.dial_desired_value.value if setpoint is None else setpoint
        readback = self.dial_readback_value.value if readback is None else setpoint
        high_limit = self.dial_high_limit.value if high_limit is None else high_limit
        low_limit = self.dial_low_limit.value if low_limit is None else low_limit
        offset = self.user_offset.value if offset is None else offset
        direction = self.user_direction.value if direction is None else direction
        # Set the various values
        pvs = [
            (setpoint, self.parent),
            (readback, self.user_readback_value),
            (high_limit, self.user_high_limit),
            (low_limit, self.user_low_limit),
        ]
        for dial_val, user_pv in pvs:
            user_val = self._dial_to_user_value(
                dial_val, offset=offset, direction=direction
            )
            print(f"{dial_val} -> {user_val}")
            await user_pv.write(user_val)

    def _user_to_offset(self, user) -> float:
        """Convert a *user* value (most likely a setpoint) to a calibration
        offset.

        Uses the current calibration direction and dial setpoint.

        Returns
        =======
        float
          The newly calculated user offset value.

        """
        dial = self.dial_desired_value.value
        direction = self.user_direction.value
        direction = -1 if direction == "Neg" else 1
        offset = user - dial * direction
        return offset

    def _user_to_dial_value(self, user) -> float:
        """Convert a *user* value (most likely a setpoint) to a dial value.

        Uses the current calibration offset/direction.

        Returns
        =======
        float
          The newly calculated dial value.

        """
        offset = self.user_offset.value
        direction = self.user_direction.value
        direction = -1 if direction == "Neg" else 1
        dial = (user - offset) / direction
        return dial

    def _dial_to_user_value(self, dial, offset=None, direction=None) -> float:
        """Convert a *dial* value (e.g. readback or setpoint) to user value.

        Uses the current calibration offset/direction unless *offset*
        or *direction* is given.

        Returns
        =======
        float
          The newly calculated user value.

        """
        offset = self.user_offset.value if offset is None else offset
        direction = self.user_direction.value if direction is None else direction
        direction = -1 if direction == "Neg" else 1
        return dial * direction + offset

    @MotorFields.user_low_limit.putter
    async def user_low_limit(self, instance, value):
        await self.dial_low_limit.write(self._user_to_dial_value(value))

    @MotorFields.user_high_limit.putter
    async def user_high_limit(self, instance, value):
        await self.dial_high_limit.write(self._user_to_dial_value(value))

    async def check_limits(self, value, which: str):
        """Verify that the desired value is within limits.

        If not, raise SkipWrite, and set the LVIO PV. Otherwise, clear the LVIO PV.

        Parameters
        ==========
        value
          The value to check.
        which
          Either "dial" or "user"
        """
        # Check for soft limit violations
        high_limit = getattr(self, f"{which}_high_limit").value
        low_limit = getattr(self, f"{which}_low_limit").value
        within_limits = low_limit <= value <=  high_limit
        await self.limit_violation.write(not within_limits)
        if not within_limits:
            raise SkipWrite
        return value


    @MotorFields.dial_desired_value.putter
    @no_reentry
    async def dial_desired_value(self, instance, value):
        """Update related signals when the dial setpoint changes.

        - user setpoint (parent PV)
        - raw value (converted to steps)

        """
        # Check limits
        await self.check_limits(value, which="dial")
        # Update the user desired value
        new_value = self._dial_to_user_value(dial=value)
        if new_value != self.parent.value:
            await self.parent.write(new_value)
        # Update the raw desired value
        step_size = self.motor_step_size.value
        steps = value / step_size
        if steps != self.raw_desired_value.value:
            await self.raw_desired_value.write(steps)

    @MotorFields.dial_readback_value.putter
    async def dial_readback_value(self, instance, value):
        """Update the user readback when the dial readback changes."""
        new_value = self._dial_to_user_value(dial=value)
        await self.user_readback_value.write(new_value)

    @MotorFields.raw_readback_value.putter
    async def raw_readback_value(self, instance, value):
        """Propogate the raw readback value to the dial readback."""
        step_size = self.motor_step_size.value
        dial_value = value * step_size
        await self.dial_readback_value.write(dial_value )

    @MotorFields.raw_readback_value.scan(period=0.1)
    async def raw_readback_value(self, instance, async_lib):
        """Monitor for changes on the motor's position from the parent PV.

        Looks for a parent object with a ``read_motor`` method.

        """
        await self.read_motor()

    async def read_motor(self):
        """Read the motor through the parent PV and update the raw readback value."""
        # Guard to make sure the reader is defined
        if not hasattr(self.parent, 'read_motor'):
            warnings.warn(f"``read_motor`` not implemented for motor {self.parent.name}.")
            return
        # Get the new motor position from the parent PV
        new_value = await self.parent.read_motor()
        await self.raw_readback_value.write(new_value)
            
    @MotorFields.raw_desired_value.putter
    @no_reentry
    async def raw_desired_value(self, instance, value):
        """Handler for changing the raw desired value.
        
        Updates the dial_desired_value and calls the parent PVs
        ``do_move`` function to actually move the motor.

        """
        step_size = self.motor_step_size.value
        # Update the dial value
        await self.dial_desired_value.write(value * step_size)
        # Move the actual motor, if defined
        await self.do_move(target=value)

    @no_reentry
    async def do_move(self, target):
        """Perform requested motor moves.
        
        Looks for a method on the parent PV property called
        ``do_move(target: float, speed: float)`` and calls it if it is
        defined.

        Parameters
        ==========
        target
          The target value of the move, for example the raw desired
          value.

        """
        # Determine motion parameters
        step_size = self.motor_step_size.value
        speed = self.velocity.value / step_size
        # Call the handler for actually moving the motor
        await self.done_moving_to_value.write(0)
        await self.motor_is_moving.write(1)
        # Guard to make sure moving is implemented
        is_implemented = hasattr(self.parent, 'do_move')
        if not is_implemented:
            warnings.warn(f"``do_move`` not implemented for motor {self.parent.name}.")
        # Try and move the motor
        try:
            if is_implemented:
                await self.parent.do_move(target, speed=speed)
        finally:
            # Report that the motor is done moving
            await self.motor_is_moving.write(0)
            self.async_lib.sleep(self.readback_settle_time.value)
            await self.done_moving_to_value.write(1)

    @MotorFields.user_offset.putter
    async def user_offset(self, instance, value):

        """Update the user setpoint and readback when the calibration offset changes."""
        # Convert the setpoint
        new_value = self._dial_to_user_value(
            dial=self.dial_desired_value.value, offset=value
        )
        await self.parent.write(new_value)
        # Convert the readback value
        new_value = self._dial_to_user_value(
            dial=self.dial_readback_value.value, offset=value
        )
        await self.user_readback_value.write(new_value)

    @MotorFields.user_direction.putter
    async def user_direction(self, instance, value):
        """Update the user setpoint and readback when the calibration direction changes."""
        # Convert the setpoint
        new_value = self._dial_to_user_value(
            dial=self.dial_desired_value.value, direction=value
        )
        await self.parent.write(new_value)
        # Convert the readback value
        new_value = self._dial_to_user_value(
            dial=self.dial_readback_value.value, direction=value
        )
        await self.user_readback_value.write(new_value)

    @MotorFields.freeze_offset.putter
    async def freeze_offset(self, instance, value):
        """The fields VOF and FOF are intended for use in backup/restore
        operations; any write to them will drive the FOFF field to
        "Variable" (VOF) or "Frozen" (FOF).

        """
        await self.offset_freeze_switch.write(1)
        return 0

    @MotorFields.variable_offset.putter
    async def variable_offset(self, instance, value):
        """The fields VOF and FOF are intended for use in backup/restore
        operations; any write to them will drive the FOFF field to
        "Variable" (VOF) or "Frozen" (FOF).

        """
        await self.offset_freeze_switch.write(0)
        return 0

    @MotorFields.set_set_mode.putter
    async def set_set_mode(self, instance, value):
        """The fields SSET and SUSE are intended for use in backup/restore
        operations; any write to them will drive the SET field to
        "Set" (SSET) or "Use" (SUSE).

        """
        await self.set_use_switch.write(1)
        return 0

    @MotorFields.set_use_mode.putter
    async def set_use_mode(self, instance, value):
        """The fields SSET and SUSE are intended for use in backup/restore
        operations; any write to them will drive the SET field to
        "Set" (SSET) or "Use" (SUSE).

        """
        await self.set_use_switch.write(0)
        return 0

    @MotorFields.display_precision.startup
    async def display_precision(self, instance, async_lib):
        """Set the record's precision to match that of the parent PV."""
        precision = self.parent.precision
        await instance.write(precision)
        await self.update_field_precisions(precision)

    @MotorFields.display_precision.putter
    async def display_precision(self, instance, value):
        """Set the record's precision to match that of the parent PV."""
        await instance.group.parent.write_metadata(precision=value)
        await self.update_field_precisions(value)

    async def tweak_value(self, instance, value, direction):
        """Tweak the motor value. To be used by tweak forward and reverse.

        *direction* should be either 1 (forward) or -1 (reverse).
        """
        # Putting 0 does nothing
        if not bool(value):
            return 0
        # Figure out where to move to
        step = direction * instance.group.tweak_step_size.value
        new_val = instance.group.parent.value + step
        # Now do the moving
        await instance.group.parent.write(new_val)

    @MotorFields.tweak_motor_forward.putter
    async def tweak_motor_forward(self, instance, value):
        await self.tweak_value(instance, value, direction=1)
        return 0

    @MotorFields.tweak_motor_reverse.putter
    async def tweak_motor_reverse(self, instance, value):
        await self.tweak_value(instance, value, direction=-1)
        return 0

    async def update_field_precisions(self, precision: int):
        """Update the precision value of relevant fields.

        Not sure this is the best way, since we're modifying "private"
        attrs.

        """
        fields = [
            "dial_high_limit",
            "user_high_limit",
            "dial_low_limit",
            "user_low_limit",
            "dial_desired_value",
            "user_readback_value",
            "dial_readback_value",
            "relative_value",
            "last_rel_value",
            "tweak_step_size",
            "user_offset",
            "max_velocity",
            "velocity",
            "base_velocity",
            "bl_velocity",
            "jog_velocity",
            "seconds_to_velocity",
            "bl_seconds_to_velocity",
            "jog_accel",
            "bl_distance",
            "move_fraction",
            "proportional_gain",
            "integral_gain",
            "derivative_gain",
            "motor_step_size",
            "encoder_step_size",
            "readback_step_size",
            "retry_deadband",
            "readback_settle_time",
            "difference_dval_drbv",
            "egu_s_per_revolution",
            "speed",
            "bl_speed",
            "max_speed",
            "base_speed",
            "home_velocity",
        ]
        for fld in fields:
            attr = getattr(self, fld)
            await attr.write_metadata(precision=precision)

    @MotorFields.sync_position.putter
    async def sync_position(self, instance, value):
        # Block the putters for these values so they don't move the motor
        with no_reentry.block(self.dial_readback_value.putter, self.raw_readback_value.putter, obj=self):
            # Read the RBV values and set the setpoint values
            print(self.user_readback_value.value)
            await self.parent.write(self.user_readback_value.value, verify_value=False)
            await self.dial_desired_value.write(self.dial_readback_value.value, verify_value=False)
            await self.raw_desired_value.write(self.raw_readback_value.value, verify_value=False)
        # Reset to 0
        return 0
