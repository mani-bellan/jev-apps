select
    id as order_id,
    customer_id,
    order_date,
    status
from read_csv('{{ var("data_dir") }}/orders/dt={{ var("run_date") }}/orders.csv', header = true)
