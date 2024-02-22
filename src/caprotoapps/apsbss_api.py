from functools import partial
import asyncio


class BSSApi:
    def __init__(self, *args, proposal_api=None, esaf_api=None):
        self._prop_api = proposal_api
        self._esaf_api = esaf_api

    async def esaf_data(self, esaf_id: str):
        """Load ESAF data from the BSS database."""
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, self._esaf_api.getEsaf, esaf_id)
        return data

    async def proposal_data(self, proposal_id, cycle: str, beamline: str):
        """Load proposal data from the BSS database."""
        loop = asyncio.get_running_loop()
        get_proposal = partial(
            self._prop_api.getProposal, proposal_id, cycle=cycle, beamline=beamline
        )
        data = await loop.run_in_executor(None, get_proposal)
        return data
