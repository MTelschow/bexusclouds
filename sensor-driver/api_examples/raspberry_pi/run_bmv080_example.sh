#!/bin/bash 
# Default communication method
COMM_METHOD=""
if [ "$#" -eq 1 ]; then
    if [ "$1" == "i2c" ]; then
        COMM_METHOD="I2C"
    elif [ "$1" == "spi" ]; then
        COMM_METHOD="SPI"
    else
        COMM_METHOD=""
        echo "Error: $1 is not a valid communication method."
        exit 1
    fi
else
    echo "Usage: bash ./run_bmv080_example.sh {spi|i2c}"
    exit 1
fi

echo "Selected Communication Method: $COMM_METHOD"
MODULE=""
if [ "$COMM_METHOD" == "SPI" ]; then
    MODULE="spi_bcm2835"
elif [ "$COMM_METHOD" == "I2C" ]; then
    MODULE="i2c_bcm2835"
fi

# Check the driver availability
if ! lsmod | grep -q "$MODULE"; then
    echo "Error: $MODULE driver is not enabled."
    exit 1
fi
# Set LD_LIBRARY_PATH environment variable to the location where BMV080 SDK binaries are located
export LD_LIBRARY_PATH=$(pwd)
# Print the LD_LIBRARY_PATH for verification
echo "LD_LIBRARY_PATH: $LD_LIBRARY_PATH"
echo "Running binary..."
stdbuf -o0 ./bmv080_example