import sys
import os
import importlib.metadata
import importlib
import subprocess
import re
from packaging import version
import pkg_resources


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
    """Vérifie si pip est à la dernière version disponible."""
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
    print("🔄 Mise à jour de pip...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
            stdout=subprocess.PIPE
        )
        return True
    except subprocess.SubprocessError as e:
        print(f"❌ Échec de la mise à jour de pip: {e}")
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
        print(f"Erreur lors de la récupération des dépendances pour {package_name}")
        print(f"Message d'erreur: {e.output}")
        return None

def parse_required_packages(pip_dry_run_output):
    required = {}
    
    req_pattern = r"Requirement already satisfied: ([a-zA-Z0-9_\-]+)([<>=~].+?) in"
    
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

def check_version_conflicts(requirements, installed):
    print("\n🔍 Vérification des conflits de version :")
    conflicts = {}
    
    for pkg, req_info in requirements.items():
        if pkg in installed:
            installed_ver = installed[pkg]
            exact_version = req_info.get('exact_version')
            
            if exact_version and installed_ver != exact_version:
                print(f"⚠️ Conflit : {pkg} installé en {installed_ver}, requis {exact_version}")
                conflicts[pkg] = {
                    'installed': installed_ver,
                    'required': exact_version,
                    'dependents': get_dependent_packages(pkg)
                }
    
    if not conflicts:
        print("✅ Aucun conflit détecté.")
    
    return conflicts

def analyze_update_impact(conflicts):
    print("\n🔄 Analyse de l'impact des mises à jour:")
    
    for pkg, info in conflicts.items():
        print(f"\n📦 {pkg}: {info['installed']} → {info['required']}")
        
        if info['dependents']:
            print(f"  Les packages suivants dépendent de {pkg}:")
            for dep, dep_info in info['dependents'].items():
                req = dep_info['requirement']
                is_compatible = is_version_compatible(req, info['required'])
                status = "✅ compatible" if is_compatible else "❌ incompatible"
                print(f"  - {dep} v{dep_info['version']} ({req}) - {status}")
        else:
            print(f"  Aucun package installé ne dépend de {pkg}")

def is_version_compatible(requirement, version_str):
    """Vérifie si une version satisfait une spécification de version."""
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
        print(f"Erreur lors de la vérification de compatibilité: {e}")
        return False

def update_package_dependencies(conflicts, force=False):
    if not conflicts:
        return True
    
    print("\n🔄 Mise à jour des dépendances en conflit:")
    
    success = True
    for pkg, info in conflicts.items():
        if force or confirm_update(pkg, info, auto_yes):
            try:
                print(f"Mise à jour de {pkg} {info['installed']} → {info['required']}...")
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install", 
                    f"{pkg}=={info['required']}", "--upgrade"
                ])
                print(f"✅ {pkg} mis à jour avec succès.")
            except subprocess.CalledProcessError as e:
                print(f"❌ Échec de la mise à jour de {pkg}: {e}")
                success = False
    
    return success

def confirm_update(pkg, info, auto_yes=False):
    if auto_yes:
        print(f"Auto-confirmation pour mettre à jour {pkg} de {info['installed']} vers {info['required']} (option -y active)")
        return True
        
    dependents = len(info['dependents'])
    if dependents > 0:
        response = input(f"\n⚠️ {pkg} est utilisé par {dependents} autres packages. Mettre à jour quand même? (o/O/n/N): ")
    else:
        response = input(f"\nMettre à jour {pkg} de {info['installed']} vers {info['required']}? (o/O/n/N): ")
    
    return response.lower() == 'o' or response.upper() == 'O'

def is_present(argv, auto_yes=False):
    for package in argv:
        try:
            importlib.import_module(package.split('==')[0].split('>=')[0].split('<=')[0])
            print(f"✅ {package} est déjà installé.")
        except ImportError:
            print(f"❌ {package} n'est pas installé. Vérification des dépendances...")
            install_package_with_deps(package, auto_yes)

def install_package_with_deps(package, auto_yes=False):
    installed = get_installed_packages()
    dry_run_output = get_package_requirements(package)
    
    if dry_run_output:
        print("\nDétails d'installation:")
        print(dry_run_output)
        
        required = parse_required_packages(dry_run_output)
        if required:
            conflicts = check_version_conflicts(required, installed)
            
            if conflicts:
                analyze_update_impact(conflicts)
                if auto_yes:
                    print("\nMise à jour automatique des dépendances en conflit (option -y active)")
                    update_deps = 'o'
                else:
                    update_deps = input("\nVoulez-vous mettre à jour les dépendances en conflit? (o/O/n/N): ")
                
                if update_deps.lower() == 'o' or update_deps.upper() == 'O':
                    if update_package_dependencies(conflicts, auto_yes):
                        print("\n✅ Dépendances mises à jour avec succès.")
                    else:
                        print("\n⚠️ Certaines dépendances n'ont pas pu être mises à jour.")
                        if auto_yes:
                            print("Continuation automatique de l'installation (option -y active)")
                            should_continue = 'o'
                        else:
                            should_continue = input("Continuer l'installation malgré tout? (o/O/n/N): ")
                        
                        if should_continue.lower() != 'o' and should_continue.upper() != 'O':
                            print("Installation annulée.")
                            return
        else:
            print("⚠️ Impossible d'analyser les dépendances.")

        if auto_yes:
            print(f"Installation automatique de {package} (option -y active)")
            confirm = 'o'
        else:
            confirm = input(f"\nSouhaitez-vous installer {package}? (o/O/n/N): ")
            
        if confirm.lower() == 'o' or confirm.upper() == 'O':
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
                print(f"✅ {package} a été installé avec succès.")
            except subprocess.CalledProcessError as e:
                print(f"❌ Erreur lors de l'installation de {package}: {e}")
        else:
            print("Installation annulée.")
    else:
        print(f"⚠️ Impossible de récupérer les informations pour {package}.")

# ---------- MAIN ----------
if __name__ == "__main__":
    auto_yes = '-y' in sys.argv
    if auto_yes:
        sys.argv.remove('-y')
        print("📢 Mode automatique activé : toutes les questions auront une réponse 'oui' par défaut.")
    
    print("🔍 Vérification de pip...")
    pip_installed, pip_version = check_pip_installed()
    
    if not pip_installed:
        print("❌ pip n'est pas installé ou n'est pas accessible.")
        print("Impossible de continuer sans pip. Veuillez installer pip et réessayer.")
        sys.exit(1)
    
    print(f"✅ pip version {pip_version} est installé.")
    
    if check_pip_latest_version():
        print(f"✅ pip est déjà à la dernière version ({pip_version}).")
    else:
        if auto_yes:
            print("Mise à jour automatique de pip (option -y active)")
            update_pip_choice = 'o'
        else:
            update_pip_choice = input("Voulez-vous mettre à jour pip vers la dernière version? (o/O/n/N): ")
        
        if update_pip_choice.lower() == 'o' or update_pip_choice.upper() == 'O':
            if update_pip():
                _, new_pip_version = check_pip_installed()
                print(f"✅ pip mis à jour vers la version {new_pip_version}.")
            else:
                print("⚠️ Poursuite du programme avec la version actuelle de pip.")
    
    argc = len(sys.argv)
    argv = sys.argv

    print(f"Python exécutable utilisé: {sys.executable}")
    print("Dans un environnement virtuel?", is_virtualenv())
    print("Dans un environnement conda?", is_conda_env())

    if is_conda_env():
        print("Conda env:", os.getenv('CONDA_DEFAULT_ENV'))
    elif is_virtualenv():
        print("Environnement virtuel:", os.getenv('VIRTUAL_ENV')) 
    else:
        print("⚠️⚠️⚠️⚠️⚠️ Vous n'êtes pas dans un environnement virtuel ou conda. ⚠️⚠️⚠️⚠️")
        print("⚠️⚠️⚠️⚠️⚠️ Il est recommandé d'utiliser ce script dans un environnement isolé. ⚠️⚠️⚠️⚠️")
        
        if auto_yes:
            print("Continuation automatique (option -y active)")
            proceed = 'o'
        else:
            proceed = input("Voulez-vous continuer quand même? (o/O/n/N): ")
            
        if proceed.lower() != 'o' and proceed.upper() != 'O':
            print("Opération annulée.")
            sys.exit(1)
    
    if argc < 2:
        print("Usage: python script.py [-y] nom_du_package [nom_du_package2 ...]")
        print("  -y : Répondre 'oui' automatiquement à toutes les questions")
        sys.exit(1)
    
    packages_to_check = sys.argv[1:]
    is_present(packages_to_check, auto_yes)