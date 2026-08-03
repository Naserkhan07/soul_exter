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
    prompt_lower = prompt.lower().strip()
    response_logs = []
    
    # ----------------------------------------------------
    # CONVERSATIONAL / GREETINGS
    # ----------------------------------------------------
    if prompt_lower in ["hi", "hello", "hey", "wake up"]:
        response_logs.append("🤖 [JARVIS] Hello, sir. All systems are online and running at optimal efficiency.")
        response_logs.append("[SYSTEM] Ready for your engineering commands.")
        return response_logs
    elif "who are you" in prompt_lower:
        response_logs.append("🤖 [JARVIS] I am your autonomous AI software engineer. I exist to build, test, and deploy software for you.")
        return response_logs
        
    # ----------------------------------------------------
    # CORE ENGINEERING COMMANDS
    # ----------------------------------------------------
    if "design" in prompt_lower or "architecture" in prompt_lower or "diagram" in prompt_lower:
        system_name = prompt_lower.split("for")[-1].strip() if "for" in prompt_lower else "Scalable System"
        response_logs.append(design_system_architecture(system_name))
    elif "ci/cd" in prompt_lower or "pipeline" in prompt_lower or "github actions" in prompt_lower:
        response_logs.append(setup_cicd_pipeline())
    elif "profile" in prompt_lower or "optimize" in prompt_lower or "bottleneck" in prompt_lower:
        response_logs.append(scaffold_performance_profiler())
    elif "deploy" in prompt_lower or "live" in prompt_lower:
        project = "jarvis_generated_web"
        response_logs.append(deploy_to_internet(project))
    elif "auto loop" in prompt_lower or "continuous" in prompt_lower or "self heal" in prompt_lower:
        response_logs.append(start_autonomous_loop("infinite_app.py"))
    elif "sandbox" in prompt_lower or "docker" in prompt_lower or "safe test" in prompt_lower:
        response_logs.append(test_in_docker_sandbox("infinite_app.py"))
    elif "cloud" in prompt_lower or "generate" in prompt_lower or "write custom code" in prompt_lower:
        query = prompt_lower.split("generate")[-1].strip() if "generate" in prompt_lower else prompt_lower
        response_logs.append(generate_infinite_code(query))
    elif "website" in prompt_lower or "igloo" in prompt_lower:
        response_logs.append(scaffold_3d_website("jarvis_generated_web"))
    elif "game" in prompt_lower or "free fire" in prompt_lower:
        response_logs.append(scaffold_3d_game("jarvis_generated_game"))
    elif "ghost" in prompt_lower or "watch" in prompt_lower:
        response_logs.append(start_ghost_coder())
    elif "scrape" in prompt_lower or "news" in prompt_lower:
        response_logs.append(scrape_data())
    elif "app" in prompt_lower or "mobile" in prompt_lower:
        response_logs.append(scaffold_mobile_app())
    elif "analyze" in prompt_lower or "data" in prompt_lower or "graph" in prompt_lower:
        response_logs.append(scaffold_data_analysis())
    elif "security" in prompt_lower or "scan" in prompt_lower or "defend" in prompt_lower:
        response_logs.append(scan_local_code_for_secrets())
    elif "fine tune" in prompt_lower or "train" in prompt_lower:
        response_logs.append(scaffold_finetuning_pipeline())
    elif "create agent" in prompt_lower or "spawn agent" in prompt_lower:
        name = prompt_lower.split("called")[-1].strip().title() if "called" in prompt_lower else "Custom Sub-Agent"
        response_logs.append(generate_new_agent(name))
    elif "find api" in prompt_lower or "search api" in prompt_lower:
        query = prompt_lower.split("api for")[-1].strip() if "api for" in prompt_lower else "machine learning"
        response_logs.append(search_public_apis(query))
    elif "find model" in prompt_lower or "huggingface" in prompt_lower:
        query = prompt_lower.split("model for")[-1].strip() if "model for" in prompt_lower else "text generation"
        response_logs.append(fetch_huggingface_models(query))
    elif "learn" in prompt_lower or "teach" in prompt_lower:
        skill = prompt_lower.split("learn")[-1].strip() if "learn" in prompt_lower else prompt_lower.split("teach")[-1].strip()
        response_logs.append(learn_advanced_skill(skill))
    else:
        response_logs.append(f"[BRAIN] Unknown intent: '{prompt}'")
        response_logs.append("[SYSTEM] Type 'design architecture', 'setup ci/cd', 'optimize code', 'deploy', 'auto loop', etc.")
            
    return response_logs
