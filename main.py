import sys
import os
import importlib.metadata
import importlib
import subprocess
import re
import logging
from packaging import version
import pkg_resources

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def check_pip_installed():
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            check=True
        )
        version_match = re.search(r'pip (\d+\.\d+\.\d+)', result.stdout)
        if version_match:
            return True, version_match.group(1)
        return True, "Version inconnue"
    except (subprocess.SubprocessError, FileNotFoundError):
        return False, None

def check_pip_latest_version():
    try:
        pip_version_info = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "pip", "--dry-run"],
            capture_output=True,
            text=True,
            check=True
        )
        
        already_satisfied = "Requirement already satisfied" in pip_version_info.stdout
        would_install = "Would install" in pip_version_info.stdout
        
        return already_satisfied and not would_install
    except subprocess.SubprocessError:
        return False

def update_pip():
    logger.info("🔄 Mise à jour de pip...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
            stdout=subprocess.PIPE
        )
        return True
    except subprocess.SubprocessError as e:
        logger.error(f"❌ Échec de la mise à jour de pip: {e}")
        return False

def is_virtualenv():
    return os.getenv('VIRTUAL_ENV') is not None

def is_conda_env():
    return os.getenv('CONDA_DEFAULT_ENV') is not None

def get_installed_packages():
    return {pkg.metadata['Name'].lower(): pkg.metadata['Version'] for pkg in importlib.metadata.distributions()}

def get_dependent_packages(package_name):
    dependent_packages = {}
    
    for dist in pkg_resources.working_set:
        for req in dist.requires():
            if req.name.lower() == package_name.lower():
                dependent_packages[dist.project_name] = {
                    'version': dist.version,
                    'requirement': str(req)
                }
    
    return dependent_packages

def get_package_requirements(package_name):
    try:
        output = subprocess.check_output(
            [sys.executable, "-m", "pip", "install", package_name, "--dry-run", "--ignore-installed"],
            stderr=subprocess.STDOUT,
            text=True
        )
        return output
    except subprocess.CalledProcessError as e:
        logger.error(f"Erreur lors de la récupération des dépendances pour {package_name}")
        logger.error(f"Message d'erreur: {e.output}")
        return None

def parse_required_packages(pip_dry_run_output):
    required = {}
    
    req_pattern = r"Requirement already satisfied: ([a-zA-Z0-9_\-]+)([<>=~!].+?) in"
    
    would_install_pattern = r"Would install (.+)"
    
    for line in pip_dry_run_output.splitlines():
        req_match = re.search(req_pattern, line)
        if req_match:
            name = req_match.group(1).lower()
            version_req = req_match.group(2).strip()
            required[name] = {'version_req': version_req, 'exact_version': None}
        
        would_match = re.search(would_install_pattern, line)
        if would_match:
            packages = would_match.group(1).split()
            for pkg in packages:
                parts = pkg.split('-')
                if len(parts) >= 2:
                    name = '-'.join(parts[:-1]).lower()
                    exact_version = parts[-1]
                    if name in required:
                        required[name]['exact_version'] = exact_version
                    else:
                        required[name] = {'version_req': f"=={exact_version}", 'exact_version': exact_version}
    
    return required

def safe_get_dependent_packages(pkg):
    try:
        return get_dependent_packages(pkg)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des dépendants de {pkg}: {e}")
        return {}

def extract_compatible_version(version_req):
    try:
        if '==' in version_req:
            return version_req.split('==')[1]
        elif '>=' in version_req:
            return version_req.split('>=')[1]
        elif '<=' in version_req:
            return version_req.split('<=')[1]
        return None
    except:
        return None

def meets_version_requirement(installed_ver, version_req):
    try:
        if '==' in version_req:
            req_ver = version_req.split('==')[1]
            return installed_ver == req_ver
        elif '>=' in version_req:
            req_ver = version_req.split('>=')[1]
            return version.parse(installed_ver) >= version.parse(req_ver)
        elif '<=' in version_req:
            req_ver = version_req.split('<=')[1]
            return version.parse(installed_ver) <= version.parse(req_ver)
        return True
    except:
        return False

def check_version_conflicts(requirements, installed):
    logger.info("\n🔍 Vérification des conflits de version :")
    conflicts = {}
    
    for pkg, req_info in requirements.items():
        if pkg in installed:
            installed_ver = installed[pkg]
            exact_version = req_info.get('exact_version')
            version_req = req_info.get('version_req', '')
            
            if exact_version and installed_ver != exact_version:
                try:
                    is_downgrade = version.parse(installed_ver) > version.parse(exact_version)
                except:
                    is_downgrade = None
                
                logger.warning(f"⚠️ Conflit : {pkg} installé en {installed_ver}, requis {exact_version}")
                conflicts[pkg] = {
                    'installed': installed_ver,
                    'required': exact_version,
                    'is_downgrade': is_downgrade,
                    'dependents': safe_get_dependent_packages(pkg)
                }
            elif version_req and not meets_version_requirement(installed_ver, version_req):
                compatible_version = extract_compatible_version(version_req)
                
                logger.warning(f"⚠️ Conflit : {pkg} installé en {installed_ver}, mais {version_req} est requis")
                if compatible_version:
                    logger.info(f"   → Version compatible suggérée: {compatible_version}")
                
                conflicts[pkg] = {
                    'installed': installed_ver,
                    'required': compatible_version or '?',
                    'version_req': version_req,
                    'dependents': safe_get_dependent_packages(pkg)
                }
    
    if not conflicts:
        logger.info("✅ Aucun conflit détecté.")
    
    return conflicts

def analyze_update_impact(conflicts):
    logger.info("\n🔄 Analyse de l'impact des mises à jour:")
    
    for pkg, info in conflicts.items():
        action = "DOWNGRADE" if info.get('is_downgrade') else "mise à jour"
        logger.info(f"\n📦 {pkg}: {info['installed']} → {info['required']} ({action})")
        
        if info['dependents']:
            logger.info(f"  Les packages suivants dépendent de {pkg}:")
            for dep, dep_info in info['dependents'].items():
                req = dep_info['requirement']
                is_compatible = is_version_compatible(req, info['required'])
                status = "✅ compatible" if is_compatible else "❌ incompatible"
                logger.info(f"  - {dep} v{dep_info['version']} ({req}) - {status}")
        else:
            logger.info(f"  Aucun package installé ne dépend de {pkg}")
            
        if info.get('is_downgrade'):
            logger.warning(f"  ⚠️ Attention: Le downgrade de {pkg} peut causer des problèmes de compatibilité!")

def is_version_compatible(requirement, version_str):
    try:
        spec_match = re.search(r'([<>=~!].+)', requirement)
        if not spec_match:
            return True
        
        version_spec = spec_match.group(1)
        pkg_name = requirement.split(version_spec)[0].strip()
        
        req = f"{pkg_name}{version_spec}"
        
        return pkg_resources.require(req)[0].version == version_str
    except (pkg_resources.VersionConflict, pkg_resources.DistributionNotFound):
        return False
    except Exception as e:
        logger.error(f"Erreur lors de la vérification de compatibilité: {e}")
        return False

def confirm_update(pkg, info, auto_yes=False):
    if auto_yes:
        logger.info(f"Auto-confirmation pour {'downgrader' if info.get('is_downgrade') else 'mettre à jour'} "
              f"{pkg} de {info['installed']} vers {info['required']} (option -y active)")
        return True
    
    action = "downgrader" if info.get('is_downgrade') else "mettre à jour"
    
    dependents = len(info['dependents'])
    if info.get('is_downgrade'):
        logger.warning(f"\n⚠️ ATTENTION: Vous allez downgrader {pkg} de {info['installed']} vers {info['required']}.")
        logger.warning("   Cela peut causer des problèmes de compatibilité avec d'autres packages.")
    
    if dependents > 0:
        response = input(f"\n⚠️ {pkg} est utilisé par {dependents} autres packages. {action.capitalize()} quand même? (o/O/n/N): ")
    else:
        response = input(f"\n{action.capitalize()} {pkg} de {info['installed']} vers {info['required']}? (o/O/n/N): ")
    
    return response.lower() == 'o' or response.upper() == 'O'

def resolve_dependency_conflict(package, version_conflict, auto_yes=False):
    logger.info(f"\n🔄 Résolution automatique des conflits pour installer {package}...")
    
    sorted_conflicts = sorted(version_conflict.items(), 
                             key=lambda x: len(x[1]['dependents']), 
                             reverse=False)
    
    success = True
    for pkg_name, conflict_info in sorted_conflicts:
        current_version = conflict_info['installed']
        required_version = conflict_info['required']
        
        try:
            is_downgrade = version.parse(current_version) > version.parse(required_version)
            action = "downgrade" if is_downgrade else "upgrade"
        except:
            action = "mise à jour"
        
        logger.info(f"\n📦 {action.capitalize()} nécessaire: {pkg_name} {current_version} → {required_version}")
        
        dependent_pkgs = conflict_info['dependents']
        if dependent_pkgs:
            logger.warning(f"⚠️ {len(dependent_pkgs)} packages dépendent de {pkg_name}:")
            for dep, dep_info in dependent_pkgs.items():
                logger.info(f"  - {dep} v{dep_info['version']} ({dep_info['requirement']})")
        
        if not auto_yes:
            confirm = input(f"Procéder au {action} de {pkg_name}? (o/O/n/N): ")
            if confirm.lower() != 'o' and confirm.upper() != 'O':
                logger.warning(f"❌ {action.capitalize()} annulé pour {pkg_name}.")
                return False
        
        try:
            logger.info(f"🔄 {action.capitalize()} de {pkg_name} {current_version} → {required_version}...")
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", 
                f"{pkg_name}=={required_version}", "--force-reinstall"
            ], stdout=subprocess.PIPE)
            logger.info(f"✅ {pkg_name} {action} vers {required_version} avec succès.")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Échec du {action} de {pkg_name}: {e}")
            success = False
            
            if not auto_yes:
                retry = input(f"Continuer malgré l'échec du {action} de {pkg_name}? (o/O/n/N): ")
                if retry.lower() != 'o' and retry.upper() != 'O':
                    return False
    
    return success

def install_package_with_deps(package, auto_yes=False):
    package_name = package.split('==')[0].split('>=')[0].split('<=')[0]
    logger.info(f"\n📦 Vérification des dépendances pour {package}...")
    
    installed = get_installed_packages()
    dry_run_output = get_package_requirements(package)
    
    if not dry_run_output:
        logger.warning(f"⚠️ Impossible de récupérer les informations pour {package}.")
        return False
    
    logger.info("\nDétails d'installation:")
    logger.info(dry_run_output)
    
    required = parse_required_packages(dry_run_output)
    if not required:
        logger.warning("⚠️ Impossible d'analyser les dépendances.")
        return False
    
    conflicts = check_version_conflicts(required, installed)
    
    if conflicts:
        analyze_update_impact(conflicts)
        
        if auto_yes:
            logger.info("\nRésolution automatique des conflits de dépendances (option -y active)")
            resolve = True
        else:
            resolve_choice = input("\nRésoudre automatiquement les conflits de dépendances? (o/O/n/N): ")
            resolve = resolve_choice.lower() == 'o' or resolve_choice.upper() == 'O'
        
        if resolve:
            resolution_success = resolve_dependency_conflict(package, conflicts, auto_yes)
            if not resolution_success:
                logger.warning(f"⚠️ Échec de la résolution des conflits. Installation de {package} interrompue.")
                return False
            
            installed = get_installed_packages()
            
            remaining_conflicts = check_version_conflicts(required, installed)
            if remaining_conflicts:
                logger.warning("⚠️ Des conflits persistent malgré la tentative de résolution.")
                if not auto_yes:
                    force_install = input(f"Forcer l'installation de {package} malgré les conflits? (o/O/n/N): ")
                    if force_install.lower() != 'o' and force_install.upper() != 'O':
                        logger.info("Installation annulée.")
                        return False
        else:
            logger.info(f"Installation de {package} annulée.")
            return False
    
    if auto_yes:
        logger.info(f"Installation automatique de {package} (option -y active)")
        confirm = True
    else:
        install_choice = input(f"\nSouhaitez-vous installer {package}? (o/O/n/N): ")
        confirm = install_choice.lower() == 'o' or install_choice.upper() == 'O'
    
    if confirm:
        try:
            logger.info(f"🔄 Installation de {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            logger.info(f"✅ {package} a été installé avec succès.")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Erreur lors de l'installation de {package}: {e}")
            error_output = str(e.output) if hasattr(e, 'output') else "Aucun détail supplémentaire"
            logger.error(f"Détails de l'erreur: {error_output}")
            return False
    else:
        logger.info("Installation annulée.")
        return False

PACKAGE_TO_MODULE_MAP = {
    'scikit-learn': 'sklearn',
    'python-dateutil': 'dateutil',
    'PyYAML': 'yaml',
    'opencv-python': 'cv2',
    'Pillow': 'PIL',
    'email-validator': 'email_validator',
    'beautifulsoup4': 'bs4',
    'tensorflow': 'tensorflow',
    'Flask': 'flask',
    'Jinja2': 'jinja2',
    'Werkzeug': 'werkzeug',
    'itsdangerous': 'itsdangerous',
    'MarkupSafe': 'markupsafe',
    'SQLAlchemy': 'sqlalchemy',
    'alembic': 'alembic',
    'celery': 'celery',
    'boto3': 'boto3',
    'botocore': 'botocore',
    's3transfer': 's3transfer',
    'requests': 'requests',
    'urllib3': 'urllib3',
    'idna': 'idna',
    'certifi': 'certifi',
    'chardet': 'chardet',
    'setuptools': 'setuptools',
    'wheel': 'wheel',
    'pip': 'pip',
    'pytest': 'pytest',
    'tox': 'tox',
    'virtualenv': 'virtualenv',
    'numpy': 'numpy',
    'pandas': 'pandas',
    'matplotlib': 'matplotlib',
    'seaborn': 'seaborn',
    'scipy': 'scipy',
    'sympy': 'sympy',
    'networkx': 'networkx',
    'nltk': 'nltk',
    'spacy': 'spacy',
    'gensim': 'gensim',
    'torch': 'torch',
    'torchvision': 'torchvision',
    'torchaudio': 'torchaudio',
    'keras': 'keras',
    'theano': 'theano',
    'statsmodels': 'statsmodels',
    'skimage': 'skimage',
    'Pygments': 'pygments',
    'docutils': 'docutils',
    'sphinx': 'sphinx',
    'twisted': 'twisted',
    'django': 'django',
    'djangorestframework': 'rest_framework',
    'flask-restful': 'flask_restful',
    'flask-login': 'flask_login',
    'flask-wtf': 'flask_wtf',
    'wtforms': 'wtforms',
    'sqlalchemy-utils': 'sqlalchemy_utils',
    'psycopg2': 'psycopg2',
    'mysql-connector-python': 'mysql.connector',
    'pymysql': 'pymysql',
    'redis': 'redis',
    'pika': 'pika',
    'kombu': 'kombu',
    'gevent': 'gevent',
    'greenlet': 'greenlet',
    'eventlet': 'eventlet',
    'gunicorn': 'gunicorn',
    'uvicorn': 'uvicorn',
    'hypercorn': 'hypercorn',
    'fastapi': 'fastapi',
    'starlette': 'starlette',
    'aiohttp': 'aiohttp',
    'asyncio': 'asyncio',
    'trio': 'trio',
    'httpx': 'httpx',
    'websockets': 'websockets',
    'paramiko': 'paramiko',
    'fabric': 'fabric',
    'invoke': 'invoke',
    'click': 'click',
    'typer': 'typer',
    'prompt_toolkit': 'prompt_toolkit',
    'rich': 'rich',
    'colorama': 'colorama',
    'tabulate': 'tabulate',
    'pygments': 'pygments',
    'loguru': 'loguru',
    'structlog': 'structlog',
    'python-json-logger': 'pythonjsonlogger',
    'pyyaml': 'yaml',
    'jsonschema': 'jsonschema',
    'marshmallow': 'marshmallow',
    'pydantic': 'pydantic',
    'cerberus': 'cerberus',
    'voluptuous': 'voluptuous',
    'schematics': 'schematics',
    'attrs': 'attr',
    'dataclasses': 'dataclasses',
    'boltons': 'boltons',
    'more-itertools': 'more_itertools',
    'toolz': 'toolz',
    'cytoolz': 'cytoolz',
    'fn': 'fn',
    'funcy': 'funcy',
    'multipledispatch': 'multipledispatch',
    'singledispatch': 'singledispatch',
    'cachetools': 'cachetools',
    'lru-dict': 'lru',
    'diskcache': 'diskcache',
    'pylru': 'pylru',
    'joblib': 'joblib',
    'dill': 'dill',
    'cloudpickle': 'cloudpickle',
    'pickle5': 'pickle5',
    'zipp': 'zipp',
    'importlib-metadata': 'importlib_metadata',
    'importlib-resources': 'importlib_resources',
    'pkg_resources': 'pkg_resources',
    'setuptools_scm': 'setuptools_scm',
    'wheel': 'wheel',
    'build': 'build',
    'twine': 'twine',
    'pip-tools': 'piptools',
    'poetry': 'poetry',
    'flit': 'flit',
    'hatch': 'hatch',
    'conda': 'conda',
    'mamba': 'mamba',
    'nox': 'nox',
    'invoke': 'invoke',
    'fabric': 'fabric',
    'ansible': 'ansible',
    'salt': 'salt',
    'chef': 'chef',
    'puppet': 'puppet',
    'vagrant': 'vagrant',
    'docker': 'docker',
    'docker-compose': 'dockercompose',
    'kubernetes': 'kubernetes',
    'helm': 'helm',
    'terraform': 'terraform',
    'packer': 'packer',
    'vault': 'vault',
    'consul': 'consul',
    'nomad': 'nomad',
    'etcd': 'etcd',
    'zookeeper': 'zookeeper',
    'celery': 'celery',
    'rq': 'rq',
    'huey': 'huey',
    'dramatiq': 'dramatiq',
    'kombu': 'kombu',
    'pyzmq': 'zmq',
    'zerorpc': 'zerorpc',
    'grpcio': 'grpc',
    'thrift': 'thrift',
    'protobuf': 'google.protobuf',
    'avro': 'avro',
    'fastavro': 'fast',
    'jax': 'jax'
}
 

def is_present(argv, auto_yes=False):
    for package in argv:
        package_name = package.split('==')[0].split('>=')[0].split('<=')[0]
        
        module_name = PACKAGE_TO_MODULE_MAP.get(package_name, package_name)
        
        try:
            importlib.import_module(module_name)
            logger.info(f"✅ {package} est déjà installé.")
        except ImportError:
            logger.warning(f"❌ {package} n'est pas installé. Vérification des dépendances...")
            install_package_with_deps(package, auto_yes)

# ---------- MAIN ----------
if __name__ == "__main__":
    auto_yes = '-y' in sys.argv
    if auto_yes:
        sys.argv.remove('-y')
        logger.info("📢 Mode automatique activé : toutes les questions auront une réponse 'oui' par défaut.")
    
    logger.info("🔍 Vérification de pip...")
    pip_installed, pip_version = check_pip_installed()
    
    if not pip_installed:
        logger.error("❌ pip n'est pas installé ou n'est pas accessible.")
        logger.error("Impossible de continuer sans pip. Veuillez installer pip et réessayer.")
        sys.exit(1)
    
    logger.info(f"✅ pip version {pip_version} est installé.")
    
    if check_pip_latest_version():
        logger.info(f"✅ pip est déjà à la dernière version ({pip_version}).")
    else:
        if auto_yes:
            logger.info("Mise à jour automatique de pip (option -y active)")
            update_pip_choice = 'o'
        else:
            update_pip_choice = input("Voulez-vous mettre à jour pip vers la dernière version? (o/O/n/N): ")
        
        if update_pip_choice.lower() == 'o' or update_pip_choice.upper() == 'O':
            if update_pip():
                _, new_pip_version = check_pip_installed()
                logger.info(f"✅ pip mis à jour vers la version {new_pip_version}.")
            else:
                logger.warning("⚠️ Poursuite du programme avec la version actuelle de pip.")
    
    argc = len(sys.argv)
    argv = sys.argv

    logger.info(f"Python exécutable utilisé: {sys.executable}")
    logger.info(f"Dans un environnement virtuel? {is_virtualenv()}")
    logger.info(f"Dans un environnement conda? {is_conda_env()}")

    if is_conda_env():
        logger.info(f"Conda env: {os.getenv('CONDA_DEFAULT_ENV')}")
    elif is_virtualenv():
        logger.info(f"Environnement virtuel: {os.getenv('VIRTUAL_ENV')}") 
    else:
        logger.warning("⚠️⚠️⚠️⚠️⚠️ Vous n'êtes pas dans un environnement virtuel ou conda. ⚠️⚠️⚠️⚠️")
        logger.warning("⚠️⚠️⚠️⚠️⚠️ Il est recommandé d'utiliser ce script dans un environnement isolé. ⚠️⚠️⚠️⚠️")
        
        if auto_yes:
            logger.info("Continuation automatique (option -y active)")
            proceed = 'o'
        else:
            proceed = input("Voulez-vous continuer quand même? (o/O/n/N): ")
            
        if proceed.lower() != 'o' and proceed.upper() != 'O':
            logger.info("Opération annulée.")
            sys.exit(1)
    
    if argc < 2:
        logger.error("Usage: python script.py [-y] nom_du_package [nom_du_package2 ...]")
        logger.error("  -y : Répondre 'oui' automatiquement à toutes les questions")
        sys.exit(1)
    
    packages_to_check = sys.argv[1:]
    is_present(packages_to_check, auto_yes)