#!/bin/bash

export ALIBABA_CLOUD_ACCESS_KEY_ID=$INPUT_ACCESS_KEY_ID
export ALIBABA_CLOUD_ACCESS_KEY_SECRET=$INPUT_ACCESS_KEY_SECRET
echo "-----"
echo $ALIBABA_CLOUD_ACCESS_KEY_ID
echo "-----"
pass_test=1


if [ "$INPUT_TYPE" = "validate" ]; then
  for file in $INPUT_TEMPLATES
  do
    if [[ "$file" == .github* ]]; then
      continue
    fi
    if [[ "$file" == .DS_Store* ]]; then
      continue
    fi
    echo -e "\n------Testing $file------"
    if [[ "$file" != iact3-config/* ]]; then
      python /iact3.py validate -t "$file"  >> output.txt 2>&1
      cat output.txt
      if ! grep -q "LegalTemplate" output.txt; then
        pass_test=0
      fi
      rm -rf output.txt
    fi
  done
  if [ $pass_test -eq 1 ]
  then
    echo "status=success" >> $GITHUB_OUTPUT
	  exit 0
  else
    echo "status=fail" >> $GITHUB_OUTPUT
	  exit 1
  fi
fi


declare -a template_prefix_files=()

for file in $INPUT_TEMPLATES
do
  if [[ "$file" == .github* ]]; then
    continue
  fi
  if [[ "$file" == .DS_Store* ]]; then
    continue
  fi

  is_test_run=0
  echo -e "\n------Testing $file------"
  if [[ "$file" == iact3-config/* ]]; then
    #config file
    template_file_prefix=${file#iact3-config/}
    template_file_prefix=${template_file_prefix%.*}
    template_file_prefix=${template_file_prefix%.*}
    template_file_path=""

    if [[ " ${template_prefix_files[@]} " =~ " ${template_file_prefix} " ]]; then
      continue
    fi
    if [ -f ${template_file_prefix}.yml ]; then
      template_file_path=${template_file_prefix}.yml
      is_test_run=1
      echo "iact3 test run -t $template_file_path -c $file"
      python /iact3.py test run -t "$template_file_path" -c "$file" > /dev/null
    elif [ -f ${template_file_prefix}.yaml ]; then
      template_file_path=${template_file_prefix}.yaml
      is_test_run=1
      echo "iact3 test run -t $template_file_path -c $file"
      python /iact3.py test run -t "$template_file_path" -c "$file" > /dev/null
    else
      echo "$file has no template file. Skip testing."
    fi

    template_prefix_files+=("$template_file_prefix")
  else
    #template file
    config_file_prefix=iact3-config/${file%.*}.iact3
    config_file_path=""
    template_file_prefix=${file%.*}
    if [[ " ${template_prefix_files[@]} " =~ " ${template_file_prefix} " ]]
    then
      continue
    fi
    if [ -f ${config_file_prefix}.yml ]; then
      config_file_path=${config_file_prefix}.yml
      echo "iact3 test run -t $file -c $config_file_path"
      is_test_run=1
      python /iact3.py test run -t "$file" -c "$config_file_path" > /dev/null
    elif [ -f ${config_file_prefix}.yaml ]; then
      config_file_path=${config_file_prefix}.yaml
      echo "iact3 test run -t $file -c $config_file_path"
      is_test_run=1
      python /iact3.py test run -t "$file" -c "$config_file_path" > /dev/null
    else
      echo "iact3 validate -t $file"
      python /iact3.py validate -t "$file"  >> output.txt 2>&1
      echo $file
      cat output.txt
      if ! grep -q "LegalTemplate" output.txt; then
        pass_test=0
      fi
      rm -rf output.txt
    fi
    template_prefix_files+=("$template_file_prefix")
  fi

  if [ $is_test_run -eq 1 ]; then
    test_name=$(basename $template_file_prefix)
    test_name="test-${test_name}"
    cat iact3_outputs/${test_name}-result.json
    test_result=$(jq '.Result' iact3_outputs/${test_name}-result.json)
    if [[ $test_result != "\"Success\"" ]]; then
      pass_test=0
    fi
  fi

done

if [ $pass_test -eq 1 ]
then
  echo "status=success" >> $GITHUB_OUTPUT
	exit 0
else
  echo "status=fail" >> $GITHUB_OUTPUT
	exit 1
fi