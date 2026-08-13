FROM php:8.3-fpm

# Install PostgreSQL extension dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install PostgreSQL PHP extensions
RUN docker-php-ext-install pgsql pdo_pgsql

# Set working directory
WORKDIR /app/public