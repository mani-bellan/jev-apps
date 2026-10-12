select
    id as customer_id,
    name,
    email,
    country
from read_csv('{{ var("data_dir") }}/customers.csv', header = true)
