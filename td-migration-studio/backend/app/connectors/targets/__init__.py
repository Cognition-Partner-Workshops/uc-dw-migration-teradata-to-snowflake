"""Import every target connector module here so @register_target runs."""

from . import (  # noqa: F401
    real_bigquery,
    real_redshift,
    real_synapse,
    sim_bigquery,
    sim_redshift,
    sim_synapse,
)
