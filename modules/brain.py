import os
from modules.web_builder import scaffold_3d_website
from modules.game_builder import scaffold_3d_game
from modules.ghost_coder import start_ghost_coder
from modules.scraper import scrape_data
from modules.app_builder import scaffold_mobile_app
from modules.data_scientist import scaffold_data_analysis
from modules.security_defender import scan_local_code_for_secrets
from modules.finetuner import scaffold_finetuning_pipeline
from modules.meta_agent import generate_new_agent
from modules.api_finder import search_public_apis
from modules.open_source_brain import fetch_huggingface_models
from modules.self_evolution import learn_advanced_skill
from modules.cloud_brain import generate_infinite_code
from modules.auto_loop import start_autonomous_loop
from modules.deployer import deploy_to_internet
from modules.sandbox import test_in_docker_sandbox
from modules.architect import design_system_architecture
from modules.devops_ci import setup_cicd_pipeline
from modules.profiler import scaffold_performance_profiler

def process_prompt(prompt):
    prompt = prompt.lower()
    response_logs = []
    
    # ----------------------------------------------------
    # NEW SENIOR ENGINEER UPGRADES
    # ----------------------------------------------------
    if "design" in prompt or "architecture" in prompt or "diagram" in prompt:
        system_name = prompt.split("for")[-1].strip() if "for" in prompt else "Scalable System"
        response_logs.append(design_system_architecture(system_name))
    elif "ci/cd" in prompt or "pipeline" in prompt or "github actions" in prompt:
        response_logs.append(setup_cicd_pipeline())
    elif "profile" in prompt or "optimize" in prompt or "bottleneck" in prompt:
        response_logs.append(scaffold_performance_profiler())
        
    # ----------------------------------------------------
    # PREVIOUS UPGRADES
    # ----------------------------------------------------
    elif "deploy" in prompt or "live" in prompt:
        project = "jarvis_generated_web"
        response_logs.append(deploy_to_internet(project))
    elif "auto loop" in prompt or "continuous" in prompt or "self heal" in prompt:
        response_logs.append(start_autonomous_loop("infinite_app.py"))
    elif "sandbox" in prompt or "docker" in prompt or "safe test" in prompt:
        response_logs.append(test_in_docker_sandbox("infinite_app.py"))
    elif "cloud" in prompt or "generate" in prompt or "write custom code" in prompt:
        query = prompt.split("generate")[-1].strip() if "generate" in prompt else prompt
        response_logs.append(generate_infinite_code(query))
    elif "website" in prompt or "igloo" in prompt:
        response_logs.append(scaffold_3d_website("jarvis_generated_web"))
    elif "game" in prompt or "free fire" in prompt:
        response_logs.append(scaffold_3d_game("jarvis_generated_game"))
    elif "ghost" in prompt or "watch" in prompt:
        response_logs.append(start_ghost_coder())
    elif "scrape" in prompt or "news" in prompt:
        response_logs.append(scrape_data())
    elif "app" in prompt or "mobile" in prompt:
        response_logs.append(scaffold_mobile_app())
    elif "analyze" in prompt or "data" in prompt or "graph" in prompt:
        response_logs.append(scaffold_data_analysis())
    elif "security" in prompt or "scan" in prompt or "defend" in prompt:
        response_logs.append(scan_local_code_for_secrets())
    elif "fine tune" in prompt or "train" in prompt:
        response_logs.append(scaffold_finetuning_pipeline())
    elif "create agent" in prompt or "spawn agent" in prompt:
        name = prompt.split("called")[-1].strip().title() if "called" in prompt else "Custom Sub-Agent"
        response_logs.append(generate_new_agent(name))
    elif "find api" in prompt or "search api" in prompt:
        query = prompt.split("api for")[-1].strip() if "api for" in prompt else "machine learning"
        response_logs.append(search_public_apis(query))
    elif "find model" in prompt or "huggingface" in prompt:
        query = prompt.split("model for")[-1].strip() if "model for" in prompt else "text generation"
        response_logs.append(fetch_huggingface_models(query))
    elif "learn" in prompt or "teach" in prompt:
        skill = prompt.split("learn")[-1].strip() if "learn" in prompt else prompt.split("teach")[-1].strip()
        response_logs.append(learn_advanced_skill(skill))
    else:
        response_logs.append(f"[BRAIN] Unknown intent: '{prompt}'")
        response_logs.append("[SYSTEM] Type 'design architecture', 'setup ci/cd', 'optimize code', 'deploy', 'auto loop', etc.")
            
    return response_logs
