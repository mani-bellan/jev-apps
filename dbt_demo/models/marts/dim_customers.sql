-- One row per customer with their order count. Feeds the marketing newsletter list.
select
    c.customer_id,
    c.name,
    c.email,
    c.country,
    count(o.order_id) as order_count
from {{ ref('stg_customers') }} as c
left join {{ ref('stg_orders') }} as o using (customer_id)
group by all
