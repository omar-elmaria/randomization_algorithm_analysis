This is a utility for running switchback allocation. The folder contains the following files,
1. experiment-allocation.jar - The jar has a client for calling the switchback allocation function.
2. input.csv - CSV file with order data in the format orderId,zone,orderTime
3. run-allocation.sh - The script file that reads order data from the input.csv and calls the client jar. 
   Following parameters are required for the execution of the script,
	-w Switchback window in hours
	-v Number of variants (including Control)
	-t Experiment start time in the format YYY-MM-DDThh:mm:ssZ
	-k Experiment key [Optional]
	-s Experiment salt[Optional]

   Usage: ./run-allocation.sh -w 3.0 -v 3 -t 2022-11-03T10:15:30Z -k 28115 -s DB0720FD-326E-407F-9EA2-512BF8154DDE

The results of the allocation will be stored in the file output.csv in the format orderId,variant.
Note: The output file will be overwritten each time the script is run.
      Java must be installed in the system and JAVA_HOME must be set in the environment variable to run the script.

In python, you can run the shell script using the subprocess command
import subprocess
subprocess.run([
    "sh",
    "./run-allocation.sh",
    "-w",
    "3.0",
    "-v",
    "3",
    "-t",
    "2022-12-03T10:15:30Z",
    "-k",
    "28115",
    "-s",
    "DB0720FD-326E-407F-9EA2-512BF8154KLL"    
])