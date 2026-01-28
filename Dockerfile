FROM python:3.14-slim

WORKDIR /app

# Install MySQL connector and helpers
RUN pip install mysql-connector-python prettytable python-dotenv

# Copy
COPY . .

# Keep container alive for manual exec
CMD ["tail", "-f", "/dev/null"]

