select {{ batch_id() }} as computed_batch
where {{ batch_id() }} <> {{ var('batch_id') }} or {{ batch_id() }} is null
