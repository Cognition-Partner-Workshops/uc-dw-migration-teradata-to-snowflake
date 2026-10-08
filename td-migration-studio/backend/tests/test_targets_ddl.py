import pytest
from target_fixtures import GEOLOCATION, ORDERS, plan

from app.connectors.registry import get_target_meta
from app.connectors.targets.base import TargetConfigError
from app.connectors.targets.sim_bigquery import SimulatedBigQuery
from app.connectors.targets.sim_redshift import SimulatedRedshift
from app.connectors.targets.sim_synapse import SimulatedSynapse


def ddl(cls, target, table, options, connection=None):
    return cls(get_target_meta(target), connection or {}, {}).render_ddl(plan(target, table, options))


SYNAPSE = """CREATE TABLE [retail_dw].[orders]
(
    [order_id] CHAR(32) NOT NULL,
    [customer_id] CHAR(32) NOT NULL,
    [order_status] VARCHAR(20),
    [order_purchase_timestamp] DATETIME2(0) NOT NULL,
    [order_delivered_customer_date] DATETIME2(0),
    CONSTRAINT [pk_orders] PRIMARY KEY NONCLUSTERED ([order_id]) NOT ENFORCED
)
WITH
(
    DISTRIBUTION = HASH([order_id]),
    CLUSTERED COLUMNSTORE INDEX,
    PARTITION ([order_purchase_timestamp] RANGE RIGHT FOR VALUES ('2017-01-01', '2018-01-01'))
);"""

BIGQUERY = """CREATE TABLE `proj.retail_dw.orders`
(
  `order_id` STRING(32) NOT NULL,
  `customer_id` STRING(32) NOT NULL,
  `order_status` STRING(20),
  `order_purchase_timestamp` DATETIME NOT NULL,
  `order_delivered_customer_date` DATETIME,
  PRIMARY KEY (`order_id`) NOT ENFORCED
)
PARTITION BY DATETIME_TRUNC(`order_purchase_timestamp`, MONTH)
CLUSTER BY `customer_id`, `order_status`
OPTIONS (require_partition_filter = TRUE);"""

REDSHIFT = """CREATE TABLE "retail_dw"."orders"
(
    "order_id" CHAR(32) NOT NULL,
    "customer_id" CHAR(32) NOT NULL,
    "order_status" VARCHAR(40),
    "order_purchase_timestamp" TIMESTAMP NOT NULL,
    "order_delivered_customer_date" TIMESTAMP,
    PRIMARY KEY ("order_id")
)
DISTSTYLE KEY
DISTKEY ("order_id")
COMPOUND SORTKEY ("order_purchase_timestamp")
ENCODE AUTO;"""


def test_synapse_ddl_snapshot():
    opts = {
        "distribution": "HASH",
        "distribution_column": "order_id",
        "partition_column": "order_purchase_timestamp",
    }
    assert ddl(SimulatedSynapse, "synapse", ORDERS, opts) == SYNAPSE


def test_bigquery_ddl_snapshot():
    opts = {
        "partition_column": "order_purchase_timestamp",
        "clustering_columns": ["customer_id", "order_status"],
        "require_partition_filter": True,
    }
    assert ddl(SimulatedBigQuery, "bigquery", ORDERS, opts, {"project": "proj"}) == BIGQUERY


def test_redshift_ddl_snapshot():
    opts = {"diststyle": "KEY", "distkey": "ORDER_ID", "sortkeys": "order_purchase_timestamp"}
    assert ddl(SimulatedRedshift, "redshift", ORDERS, opts) == REDSHIFT


def test_synapse_variants():
    out = ddl(SimulatedSynapse, "synapse", GEOLOCATION, {"distribution": "REPLICATE", "index_type": "HEAP"})
    assert "DISTRIBUTION = REPLICATE,\n    HEAP" in out and "PRIMARY KEY" not in out  # non-unique PI: no PK
    opts = {
        "index_type": "CLUSTERED_INDEX",
        "partition_column": "order_purchase_timestamp",
        "partition_boundaries": ["2017-07-01"],
    }
    out = ddl(SimulatedSynapse, "synapse", ORDERS, opts)
    assert "CLUSTERED INDEX ([order_id])" in out and "FOR VALUES ('2017-07-01')" in out


def test_bigquery_date_and_day_partitions():
    out = ddl(
        SimulatedBigQuery,
        "bigquery",
        ORDERS,
        {"partition_column": "order_purchase_timestamp", "partition_granularity": "DAY"},
    )
    assert "PARTITION BY DATE(`order_purchase_timestamp`)" in out and out.startswith(
        "CREATE TABLE `retail_dw.orders`"
    )


@pytest.mark.parametrize(
    "cls,target,table,options,message",
    [
        (SimulatedBigQuery, "bigquery", ORDERS, {"clustering_columns": ["order_id"] * 5}, "at most 4"),
        (
            SimulatedBigQuery,
            "bigquery",
            ORDERS,
            {"partition_column": "order_status"},
            "DATE, DATETIME, TIMESTAMP",
        ),
        (
            SimulatedBigQuery,
            "bigquery",
            ORDERS,
            {"require_partition_filter": True},
            "needs a partition_column",
        ),
        (SimulatedBigQuery, "bigquery", ORDERS, {"partition_column": "nope"}, "not a column"),
        (SimulatedRedshift, "redshift", ORDERS, {"diststyle": "KEY"}, "requires 'distkey'"),
        (SimulatedRedshift, "redshift", ORDERS, {"diststyle": "EVEN", "distkey": "order_id"}, "only valid"),
        (SimulatedSynapse, "synapse", ORDERS, {"distribution": "HASH"}, "requires 'distribution_column'"),
        (
            SimulatedSynapse,
            "synapse",
            GEOLOCATION,
            {"partition_column": "geolocation_lat"},
            "partition_boundaries",
        ),
    ],
)
def test_invalid_options_raise_clear_errors(cls, target, table, options, message):
    with pytest.raises(TargetConfigError, match=message):
        ddl(cls, target, table, options)


def test_bigquery_bignumeric_cluster_is_allowed_but_float_is_not():
    from app.contracts.models import ColumnMeta

    geo = GEOLOCATION.model_copy(
        update={
            "columns": GEOLOCATION.columns
            + [ColumnMeta(name="f", ordinal=5, base_type="FLOAT", td_type="FLOAT", td_type_code="F")]
        }
    )
    assert "CLUSTER BY `geolocation_lat`" in ddl(
        SimulatedBigQuery, "bigquery", geo, {"clustering_columns": ["geolocation_lat"]}
    )
    with pytest.raises(TargetConfigError, match="cannot cluster"):
        ddl(SimulatedBigQuery, "bigquery", geo, {"clustering_columns": ["f"]})
