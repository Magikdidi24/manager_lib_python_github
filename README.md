This script is designed to ASSIST you when encountering issues with conflicting library versions.
It is recommended to run it within a virtual environment.
This script has not been tested with edge cases or heavy stress tests. Use with caution.
So :
1) clone repository
2) cd manager_lib_python_github
3) pip install -r requirements.txt
4) python main.py [args]
**EXEMPLE**
python main.py "scipy>=1.12.0" "matplotlib>=3.8.0" "pandas==1.3.0" "numpy"
