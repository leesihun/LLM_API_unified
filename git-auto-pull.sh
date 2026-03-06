git clone https://github.com/LeeSihun/LLM_API temp_repo
rsync -a temp_repo/ .
rm -rf temp_repo
echo "Pulled latest changes from remote repository."