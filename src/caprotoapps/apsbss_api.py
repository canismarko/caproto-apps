"""Client for the APS data management REST API.

Mostly this is to provide an awaitable interface for caproto to use.

REST API Endpoints
==================

| Endpoint                           | Meaning                                         |
|------------------------------------+-------------------------------------------------|
| /dm/proposals/2023-1/25-ID-C       | Array of proposals at 25-ID-C for 2023-1 cycle. |
| /dm/esafsBySectorAndYear/20/2020   | ESAFs for sector 20 in year 2020.               |
| /dm/proposals/2022-2/20-BM-B/12345 | Propsal # 12345 during 2022-2 cycle at 20-BM-B  |
| /dm/esafs/12345                    | ESAF #12345                                     |

"""
from pathlib import Path

import aiohttp
from aiohttp.client_exceptions import ClientResponseError
from functools import partial
import asyncio
from typing import Mapping


class ProposalNotFound(RuntimeError):
    """The proposal number cannot be found in the database."""
    ...


class BSSApi:
    """An API to interact with the APS beamline scheduling system.

    Normally, only the parameter *dm_host* is required and will be
    used to create the needed API clients. Alternately, the proposal
    and ESAF API clients may be given independently (intended for
    testing).

    Parameters
    ==========
    dm_host
      The hostname, port for the data management web
      server. E.g. "https://dm.example.com:3538"
    proposal_api
      A BSS API client.
    esaf_api
      An ESAF API client.
    """
    def __init__(self, dm_host: str = "https://localhost"):
        # Remove trailing '/' so we don't double up later
        self.host = dm_host.strip('/')

    async def get_url(self, url):

        async with aiohttp.ClientSession() as session:
            async with session.get(url, verify_ssl=False) as response:
                response.raise_for_status()
                return await response.json()

    async def esaf_data(self, esaf_id: str) -> Mapping:
        """Load ESAF data from the BSS database."""
        url = f"{self.host}/dm/esafs/{esaf_id}/"
        return await self.get_url(url)

    async def proposal_data(self, proposal_id, cycle: str, beamline: str) -> Mapping:
        """Load proposal data from the BSS database."""
        url = f"{self.host}/dm/proposals/{cycle}/{beamline}/{proposal_id}/"
        try:
            return await self.get_url(url)
        except ClientResponseError:
            raise ProposalNotFound(f"ID: {proposal_id}, beamline: {beamline}, cycle: {cycle}")
