-- One row per order with its payment total. Feeds revenue reporting and invoices.
select
    o.order_id,
    o.customer_id,
    o.order_date,
    o.status,
    coalesce(sum(p.amount), 0) as amount
from {{ ref('stg_orders') }} as o
left join {{ ref('stg_payments') }} as p using (order_id)
group by all
