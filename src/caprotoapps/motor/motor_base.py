from caproto.server.records import MotorFields, register_record
from caproto.asyncio.client import Context


from pprint import pprint

@register_record
class MotorFieldsBase(MotorFields):

    parent_context: Context
    _record_type = 'motor_base'
    
    def __init__(self, *args, axis_num: int = 99, **kwargs):
        self.axis_num = axis_num
        super().__init__(*args, **kwargs)
        self.parent_context = None
        self.parent_pv = None
        self.parent_subscription = None

    # @property
    # def driver(self):
    #     # Find the root of the IOC
    #     obj = self
    #     while True:
    #         # Find the next node up the tree
    #         try:
    #             parent = obj.parent
    #         except AttributeError:
    #             parent = obj.group
    #         # See if the next node up is the root
    #         if parent is None:
    #             # It's the root node, so quit
    #             break
    #         else:
    #             obj = parent
    #     return obj.driver

    # async def move_axis(self, instance, new_pos, vel, acc, relative):
    #     # Indicate that the axis is moving
    #     await instance.group.motor_is_moving.write(1)
    #     await instance.group.done_moving_to_value.write(0)
    #     # Do the move in a separate thread
    #     loop = self.async_lib.library.get_running_loop()
    #     do_mov = partial(
    #         self.do_move,
    #         new_pos=new_pos,
    #         vel=vel,
    #         acc=acc,
    #         relative=relative,
    #     )
    #     await loop.run_in_executor(None, do_mov)
    #     # Indicate that the axis is done
    #     await instance.group.motor_is_moving.write(0)
    #     await instance.group.done_moving_to_value.write(1)

    # def do_move(self, new_pos, vel, acc, relative):
    #     """A stub that decides what moving this axis means.

    #     Intended to be easily overwritten by subclasses
    #     (e.g. RobotJointFields).

    #     """
    #     self.driver.movel(new_pos, vel=vel, acc=acc, relative=relative)

    # async def tweak_value(self, instance, value, direction):
    #     """Tweak the motor value. To be used by tweak forward and reverse.

    #     *direction* should be either 1 (forward) or -1 (reverse).
    #     """
    #     # Putting 0 does nothing
    #     if not bool(value):
    #         return 0
    #     # Figure out where to move to
    #     step = direction * instance.group.tweak_step_size.value
    #     axis_num = self.parent.axis_num
    #     # Decide how fast to move
    #     acceleration = instance.group.jog_accel.value
    #     velocity = instance.group.jog_velocity.value
    #     # Do the actual moving
    #     log.info(f"Tweaking axis {axis_num} value by {step}.")
    #     new_pos = tuple((step if n == axis_num else 0) for n in range(6))
    #     await self.move_axis(
    #         instance, new_pos, vel=velocity, acc=acceleration, relative=True
    #     )

    # @MotorFields.tweak_motor_forward.putter
    # async def tweak_motor_forward(self, instance, value):
    #     await self.tweak_value(instance, value, direction=1)
    #     return 0

    # @MotorFields.tweak_motor_reverse.putter
    # async def tweak_motor_reverse(self, instance, value):
    #     await self.tweak_value(instance, value, direction=-1)
    #     return 0

    # @MotorFields.description.startup
    # async def description(self, instance, async_lib):
    #     # Save the async lib for later use
    #     self.async_lib = async_lib
    #     # Set the fields to the PV spec properties
    #     await instance.write(self.parent.__doc__)

    # @MotorFields.jog_accel.startup
    # async def jog_accel(self, instance, async_lib):
    #     """Set the jog accel and velocity to sensible values
        
    #     This is a hack, these should really be autosaved."""
    #     await self.jog_accel.write(0.2)
    #     await self.jog_velocity.write(0.5)

    @MotorFields.dial_desired_value.startup
    async def dial_desired_value(self, instance, async_lib):
        self.parent_context = Context()
        self.parent_pv, = await self.parent_context.get_pvs(self.parent.pvname)
        self.parent_subscription = self.parent_pv.subscribe()
        self.parent_subscription.add_callback(self.handle_new_user_desired_value)
        # Look for new values coming from the parent class

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
            await self.dial_desired_value.write(self._user_to_dial_value(user_setpoint))

    async def update_user_values(self, setpoint: float=None, readback:
                           float=None, high_limit: float=None,
                           low_limit: float=None, offset: float=None,
                           direction: float=None):
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
            user_val = self._dial_to_user_value(dial_val, offset=offset, direction=direction)
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
        

    @MotorFields.dial_desired_value.putter
    async def dial_desired_value(self, instance, value):
        """Update the user setpoint when the dial setpoint changes."""
        new_value = self._dial_to_user_value(dial=value)
        await self.parent.write(new_value)

    @MotorFields.dial_readback_value.putter
    async def dial_readback_value(self, instance, value):
        """Update the user readback when the dial readback changes."""
        new_value = self._dial_to_user_value(dial=value)
        await self.user_readback_value.write(new_value)
        
    @MotorFields.user_offset.putter
    async def user_offset(self, instance, value):
        """Update the user setpoint and readback when the calibration offset changes."""
        # Convert the setpoint
        new_value = self._dial_to_user_value(dial=self.dial_desired_value.value, offset=value)
        await self.parent.write(new_value)
        # Convert the readback value
        new_value = self._dial_to_user_value(dial=self.dial_readback_value.value, offset=value)
        await self.user_readback_value.write(new_value)

    @MotorFields.user_direction.putter
    async def user_direction(self, instance, value):
        """Update the user setpoint and readback when the calibration direction changes."""
        # Convert the setpoint
        new_value = self._dial_to_user_value(dial=self.dial_desired_value.value, direction=value)
        await self.parent.write(new_value)
        # Convert the readback value
        new_value = self._dial_to_user_value(dial=self.dial_readback_value.value, direction=value)
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
    
