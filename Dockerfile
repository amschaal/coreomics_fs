# Use the official lightweight Python image
FROM python:3.12-slim

# Set a working directory inside the container
WORKDIR /app

# Copy everything from the build context (your current directory) into /app
COPY . /app

# Install any dependencies declared in requirements.txt (optional)
# If you don’t have a requirements file you can omit this line.
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# By default start an interactive shell – you can override this when you run the container
CMD ["python"]