echo "Check we are starting with clean git checkout"
if [ -n "$(git status -uno -s)" ]; 
then 
    echo "git status is not clean"; 
    false; 
fi
echo "Trying to strip out notebooks"
nbdev_clean_nbs
echo "Check that strip out was unnecessary"
git status -s # display the status to see which nbs need cleaning up
if [ -n "$(git status -uno -s)" ]; then echo -e "!!! Detected unstripped out notebooks\n!!!Remember to run nbdev_install_git_hooks"; false; fi