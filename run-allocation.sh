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
   echo -e "\t-f Input file name [Optional, Default is input.csv] Eg: orders.csv"
   exit 1 # Exit script after printing help
}

while getopts "w:v:t:k:s:f:" opt
do
   case "$opt" in
      w ) switchbackWindow="$OPTARG" ;;
      v ) numOfVariants="$OPTARG" ;;
      t ) experimentStartTime="$OPTARG" ;;
      k ) experimentKey="$OPTARG" ;;
      s ) salt="$OPTARG" ;;
      f ) inputFile="$OPTARG" ;;
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
if [ -z "$inputFile" ]
then
    INPUT=input.csv
else
    INPUT=$inputFile
fi


echo "key: $KEY"
echo "salt: $uuid"
echo "input file: $INPUT"

echo "Switchback parameters are valid, starting experiment.."

java -jar experiment-allocation.jar "$switchbackWindow" "$numOfVariants" "$experimentStartTime" "$KEY" "$uuid" "$INPUT"

