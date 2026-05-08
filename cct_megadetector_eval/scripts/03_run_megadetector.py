import os
import argparse
import subprocess
from pathlib import Path
from src.utils import load_config, ensure_dir, setup_logger

logger = setup_logger("03_run_megadetector")

def main():
    parser = argparse.ArgumentParser(description="Run MegaDetector on downloaded images.")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--force", action="store_true", help="Force rerun even if output exists")
    args = parser.parse_args()
    
    cfg = load_config(args.config)
    
    image_dir = cfg["paths"]["image_dir"]
    md_results_dir = cfg["paths"]["md_results_dir"]
    md_config = cfg["megadetector"]
    
    ensure_dir(md_results_dir)
    
    models = md_config.get("models", {})
    if not models:
        logger.error("No models configured in config.yaml under megadetector.models.")
        return
        
    for model_key, model_info in models.items():
        model_name = model_info["model_name"]
        output_json = os.path.join(md_results_dir, model_info["output_json"])
        
        if os.path.exists(output_json) and not args.force:
            logger.info(f"Skipping {model_name} because {output_json} already exists. Use --force to rerun.")
            continue
            
        logger.info(f"Running MegaDetector model '{model_name}' ...")
        
        cmd = [
            "python", "-m", "megadetector.detection.run_detector_batch",
            model_name,
            image_dir,
            output_json,
            "--quiet"
        ]
        
        if md_config.get("recursive", True):
            cmd.append("--recursive")
        if md_config.get("output_relative_filenames", True):
            cmd.append("--output_relative_filenames")
            
        try:
            logger.info(f"Executing: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            logger.info(f"Finished {model_name}. Results saved to {output_json}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to run {model_name}. Ensure 'megadetector' is installed and model_name '{model_name}' is correct in config.yaml.")
            logger.error(f"Command returned non-zero exit status {e.returncode}.")

if __name__ == "__main__":
    main()
