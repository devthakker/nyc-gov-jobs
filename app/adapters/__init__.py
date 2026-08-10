"""Source-specific job adapters."""

from app.adapters.amtrak import AmtrakJobsAdapter
from app.adapters.cuny import CUNYJobsAdapter
from app.adapters.mta import MTAJobsAdapter
from app.adapters.newyork_presbyterian import NewYorkPresbyterianAdapter
from app.adapters.northwell import NorthwellHealthAdapter
from app.adapters.nysdol import NYSDOLApprenticeshipAdapter
from app.adapters.nyc_jobs import NYCCityJobsAdapter
from app.adapters.port_authority import PortAuthorityJobsAdapter
from app.adapters.resorts_world import ResortsWorldNYCAdapter
from app.adapters.statejobsny import StateJobsNYAdapter

ADAPTERS = {
    AmtrakJobsAdapter.source_key: AmtrakJobsAdapter,
    CUNYJobsAdapter.source_key: CUNYJobsAdapter,
    MTAJobsAdapter.source_key: MTAJobsAdapter,
    NewYorkPresbyterianAdapter.source_key: NewYorkPresbyterianAdapter,
    NorthwellHealthAdapter.source_key: NorthwellHealthAdapter,
    NYSDOLApprenticeshipAdapter.source_key: NYSDOLApprenticeshipAdapter,
    NYCCityJobsAdapter.source_key: NYCCityJobsAdapter,
    PortAuthorityJobsAdapter.source_key: PortAuthorityJobsAdapter,
    ResortsWorldNYCAdapter.source_key: ResortsWorldNYCAdapter,
    StateJobsNYAdapter.source_key: StateJobsNYAdapter,
}

__all__ = [
    "ADAPTERS",
    "AmtrakJobsAdapter",
    "CUNYJobsAdapter",
    "MTAJobsAdapter",
    "NewYorkPresbyterianAdapter",
    "NorthwellHealthAdapter",
    "NYCCityJobsAdapter",
    "NYSDOLApprenticeshipAdapter",
    "PortAuthorityJobsAdapter",
    "ResortsWorldNYCAdapter",
    "StateJobsNYAdapter",
]
