import subprocess
import re
import sys
import argparse
import logging
from typing import List, Dict, Tuple, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class PipDependencyResolver:
    def __init__(self, auto_fix: bool = False, verbose: bool = False):
        self.auto_fix = auto_fix
        self.verbose = verbose
        if verbose:
            logger.setLevel(logging.DEBUG)
        
    def run_pip_check(self) -> Tuple[bool, str]:
        try:
            result = subprocess.run(
                ["pip", "check"], 
                capture_output=True, 
                text=True
            )
            return (result.returncode == 0, result.stdout or result.stderr)
        except Exception as e:
            logger.error(f"Erreur lors de l'exécution de pip check: {e}")
            return (False, f"Erreur: {e}")
    
    def parse_pip_check_output(self, output: str) -> List[Dict]:
        errors = []
        
        
        pattern = r"([a-zA-Z0-9_\-]+) ([0-9\.]+) has requirement ([a-zA-Z0-9_\-]+)([>=<~!].+), but you have ([a-zA-Z0-9_\-]+) ([0-9\.]+)"
        
        for line in output.split('\n'):
            if not line.strip():
                continue
                
            match = re.search(pattern, line)
            if match:
                package = match.group(1)
                package_version = match.group(2)
                dependency = match.group(3)
                requirement = match.group(4)
                current_dependency = match.group(5)
                current_version = match.group(6)
                
                errors.append({
                    'type': 'dependency_conflict',
                    'package': package,
                    'package_version': package_version,
                    'dependency': dependency,
                    'requirement': requirement,
                    'current_dependency': current_dependency,
                    'current_version': current_version,
                    'raw_message': line
                })
            else:
                errors.append({
                    'type': 'generic',
                    'raw_message': line
                })
                
        return errors
    
    def suggest_fix(self, error: Dict) -> Optional[str]:
        """Suggère une solution pour résoudre le problème identifié"""
        if error['type'] == 'dependency_conflict':
            package = error['package']
            dependency = error['dependency']
            requirement = error['requirement']
            
            fix_cmd = f"pip install --upgrade {dependency}{requirement}"
            
            alternative_cmd = f"pip install --upgrade {package}"
            
            return f"{fix_cmd}\n# Si cela ne fonctionne pas, essayez:\n# {alternative_cmd}"
        elif error['type'] == 'generic':
            return None
    
    def fix_error(self, command: str) -> Tuple[bool, str]:
        logger.info(f"Exécution de la commande de correction: {command}")
        try:
            result = subprocess.run(
                command.split(), 
                capture_output=True, 
                text=True
            )
            return (result.returncode == 0, result.stdout or result.stderr)
        except Exception as e:
            logger.error(f"Erreur lors de la correction: {e}")
            return (False, f"Erreur: {e}")
    
    def resolve_dependencies(self) -> bool:
        logger.info("Vérification des dépendances avec pip check...")
        success, output = self.run_pip_check()
        
        if success:
            logger.info("Aucun problème de dépendance détecté!")
            return True
        
        logger.info("Problèmes de dépendances détectés, analyse en cours...")
        errors = self.parse_pip_check_output(output)
        
        if not errors:
            logger.warning("Aucune erreur spécifique identifiée dans la sortie de pip check.")
            logger.warning(f"Sortie brute: {output}")
            return False
        
        logger.info(f"{len(errors)} problèmes de dépendances identifiés.")
        
        all_fixed = True
        for idx, error in enumerate(errors, 1):
            logger.info(f"\nProblème {idx}/{len(errors)}:")
            logger.info(f"Message: {error['raw_message']}")
            
            fix_cmd = self.suggest_fix(error)
            if not fix_cmd:
                logger.warning("Impossible de suggérer une correction automatique pour ce problème.")
                all_fixed = False
                continue
            
            logger.info(f"Solution suggérée: {fix_cmd}")
            
            if self.auto_fix:
                cmd_to_execute = fix_cmd.split('\n')[0]
                logger.info("Tentative de correction automatique...")
                fix_success, fix_output = self.fix_error(cmd_to_execute)
                
                if fix_success:
                    logger.info("Correction appliquée avec succès.")
                    if self.verbose:
                        logger.debug(f"Sortie: {fix_output}")
                else:
                    logger.error("Échec de la correction automatique.")
                    logger.error(f"Erreur: {fix_output}")
                    logger.info("Vous pouvez essayer les commandes suggérées manuellement.")
                    all_fixed = False
            else:
                logger.info("Exécutez la commande ci-dessus pour résoudre ce problème.")
                all_fixed = False
        
        if all_fixed and self.auto_fix:
            final_success, final_output = self.run_pip_check()
            if final_success:
                logger.info("\nTous les problèmes de dépendances ont été résolus avec succès!")
                return True
            else:
                logger.warning("\nCertains problèmes persistent après les corrections automatiques.")
                logger.warning(f"Sortie de pip check: {final_output}")
                return False
        
        return all_fixed

def main():
    parser = argparse.ArgumentParser(description="Résoudre les problèmes de dépendances Python identifiés par pip check")
    parser.add_argument("--auto-fix", "-a", action="store_true", help="Appliquer automatiquement les corrections suggérées")
    parser.add_argument("--verbose", "-v", action="store_true", help="Afficher des informations de débogage détaillées")
    
    args = parser.parse_args()
    
    resolver = PipDependencyResolver(auto_fix=args.auto_fix, verbose=args.verbose)
    success = resolver.resolve_dependencies()
    
    if not success and not args.auto_fix:
        logger.info("\nConseil: Exécutez avec l'option --auto-fix pour tenter de résoudre automatiquement les problèmes.")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())