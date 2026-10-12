select
    id as payment_id,
    order_id,
    method,
    amount_cents / 100.0 as amount
from read_csv('{{ var("data_dir") }}/payments.csv', header = true)
