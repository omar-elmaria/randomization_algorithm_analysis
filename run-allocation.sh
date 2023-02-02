#!/bin/bash
helpFunction()
{
   echo ""
   echo "Usage: $0 -w switchbackWindow -v numOfVariants -t experimentStartTime -k experimentKey -s salt"
   echo -e "\t-w Switchback window in hours Eg: 3.0"
   echo -e "\t-v Number of variants (including Control) Eg: 3"
   echo -e "\t-t Experiment start time in the format YYY-MM-DDThh:mm:ssZ Eg: 2022-12-03T10:15:30Z"
   echo -e "\t-k Experiment key [Optional] Eg: 28115"
   echo -e "\t-s Experiment salt[Optional] Eg: DB0720FD-326E-407F-9EA2-512BF8154DDE"
   exit 1 # Exit script after printing help
}

while getopts "w:v:t:k:s:" opt
do
   case "$opt" in
      w ) switchbackWindow="$OPTARG" ;;
      v ) numOfVariants="$OPTARG" ;;
      t ) experimentStartTime="$OPTARG" ;;
      k ) experimentKey="$OPTARG" ;;
      s ) salt="$OPTARG" ;;
      ? ) helpFunction ;; # Print helpFunction in case parameter is non-existent
   esac
done

# Print helpFunction in case parameters are empty
if [ -z "$switchbackWindow" ] || [ -z "$numOfVariants" ] || [ -z "$experimentStartTime" ]
then
   echo "Some of the required parameters are empty";
   helpFunction
fi

# Check and set optional parameters

#echo "param key: $experimentKey"
#echo "param salt: $salt"

if [ -z "$experimentKey" ] 
then
    KEY=$RANDOM
else
    KEY=$experimentKey
fi
if [ -z "$salt" ] 
then
    uuid=$(uuidgen)
else
    uuid=$salt
fi

echo "key: $KEY"
echo "salt: $uuid"

echo "Switchback parameters are valid, starting experiment.."
echo "OrderID,Variant" > output.csv

# Start reading from input file

INPUT=input.csv
OLDIFS=$IFS
IFS=','
[ ! -f $INPUT ] && { echo "$INPUT file not found"; exit 99; }
while read orderId zone orderTime
do
	java -jar experiment-allocation.jar $switchbackWindow $numOfVariants $experimentStartTime $KEY $uuid $orderId $zone $orderTime >> output.csv
done < $INPUT
IFS=$OLDIFS

echo "Allocation is complete. Results are available in output.csv file"
