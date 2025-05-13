# Salt.box conf

# Redis conf:
REDIS_HOST='redis-salt'
REDIS_USERNAME='${REDIS_USERNAME}'
REDIS_PASSWORD='${REDIS_PASSWORD}'
REDIS_SSL_USE=True
REDIS_SSL_CA_CERTS='/etc/redis/certs/ca.crt'

# Salt.box bridge conf:
# Time to live for job returns and grains (sec)
EXPIRE=604800
