import os
import json
import chromadb
from chromadb.utils import embedding_functions
import openai
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
import re
import time
from flask import Flask, request, Response, stream_with_context

api_key = "<your openai api key here>"
client = chromadb.PersistentClient(path="./chroma_db")
openai.api_key = api_key

def rag_chat(user_query,
             initial_analysis,
             customer_info,
             log,
             alert,
             collection_name="soc_playbooks_v6",
             playbooks_file="RagData/playbooks.json",
             n_results=2):
    client = chromadb.PersistentClient(path="./chroma_db")

    embedding_func = embedding_functions.OpenAIEmbeddingFunction(
        api_key=api_key,
        model_name="text-embedding-3-small"
    )

    try:
        collection = client.get_collection(
            name=collection_name,
            embedding_function=embedding_func
        )
    except:
        collection = client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_func
        )

    if collection.count() == 0:
        with open(playbooks_file, "r", encoding="utf-8") as f:
            playbooks = json.load(f)

        for pb in playbooks:
            # New-schema fields (+ id you added)
            pb_id = pb["id"]  # now required, since you added it
            title = pb.get("playbook_name", "Untitled Playbook")
            description = pb.get("description", "")

            # Flatten new recommended_actions -> remediation steps (strings)
            remediation_steps = []
            rec = pb.get("recommended_actions", {}) or {}
            for phase_key in ("containment", "eradication", "recovery_and_restore"):
                items = rec.get(phase_key, []) or []
                phase_name = phase_key.replace("_", " ").title()
                for it in items:
                    action = (it.get("action") or "").strip()
                    desc = (it.get("description") or "").strip()
                    if action and desc:
                        remediation_steps.append(f"{phase_name}: {action} — {desc}")
                    elif action:
                        remediation_steps.append(f"{phase_name}: {action}")
                    elif desc:
                        remediation_steps.append(f"{phase_name}: {desc}")

            # Derive simple verification criteria from recovery_and_restore actions
            verification_criteria = []
            for it in rec.get("recovery_and_restore", []) or []:
                action = (it.get("action") or "").strip()
                if action:
                    verification_criteria.append(f"Completed: {action}")
            if not verification_criteria:
                # keep minimal, generic checks if recovery actions are empty
                verification_criteria = [
                    "No related alerts or anomalous activity observed for 48 hours.",
                    "All containment and eradication steps completed and documented.",

                    "Affected accounts/devices restored to known-good state and monitored."
                ]

            # Build the single document string as your original code expects
            content = (
                    description + "\nRemediation:\n" +
                    "\n".join(remediation_steps) + "\nVerification:\n" +
                    "\n".join(verification_criteria)
            )

            collection.add(
                ids=[pb_id],
                documents=[content],
                metadatas=[{"title": title}]
            )
    results = collection.query(
        query_texts=[user_query],
        n_results=n_results
    )

    retrieved_texts = results['documents'][0]
    playbook = "\n\n".join(retrieved_texts)

    ########################################################################################################################
    # Final prompt that is being sent in with the following parameters:
    # Alerts, Logs, initial analysis, customer info and playbook (RAG)
    ########################################################################################################################

    prompt = f"""
You are going to act as an assistance for a Tier 1 MDR SOC analyst. 
Your goal is to help the analyst create a template for a SOC report, based on: 
1) The initial alert and hypothesis provided by the analyst. 
2) The logs that has been tagged as relevant by the analyst. 

Return a template for a SOC report based on the inpt data. 

The following data will be input and utilized:

The SOC analysts got the following alert:
{alert}

The logs that the analyst has tagged as important evidence for the report/indicent:
{log}

The Tier 1 SOC analyst has done an initial analysis, and come up with an hypothesis what this activity is. 
This initial analysis and hypothesis will be the foundation for the alert summary:  
{initial_analysis}

The client company that has been affect is:
{customer_info}

Based on the customer contract type, different immediate REMEDIATION actions (from the playbook) can be executed by the SOC: 
If the customer has mdr_contract_type=EDR then the Tier 1 SOC analyst can only do remediation actions that are endpoint focused. The customer must do the rest. 
If the customer has mdr_contract_type=XDR then the Tier 1 SOC analyst can do more extensive remediation actions across multiple security layers, like networks or cloud applications.  

Use the following playbook information to help generate the report template:
{playbook}

With all this information, fill in the following report template strictly, in a concise way, suitable for sending to a MDR customer. 
All parts of the report must be precise, with no unnecessary tangents or unnecessarily complicated wording. 
The report should be simple and understandable for MDR customers. 

Fill in the following template:
------------------------------------------------------------------------------------------------------------------------------
Title:
Date:
Alert Type/Category: e.g., Attempted Compromise
Severity: Low / Medium / High / Critical
Analyst Name: Let this be blank, for the analyst to fill in
Case #:

# DETECTION AND ANALYSIS

## Alert Summary:
* Write an "Alert Summary" for an MDR SOC report.
Follow these instructions exactly:
1. Heavily base the alert summary on the initial analysis and hypothesis that the analyst has written. If any sources, or citations are included, keep them in the text, and include a list of the sources at the end of this section, it its own section called ### References: 
2. Begin with a single sentence describing the activity, and where the detection originated (e.g., "Microsoft Defender detected X on the host Y by the user Z."). 
3. Provide a brief description of the attack type or tactic, max two sentences. Use internal SOC playbooks or general security knowledge to describe what the attack is and what it aims to achieve.
4. Integrate all key findings and evidence into the summary naturally (no bullet points). Mention relevant details such as processes executed, suspicious commands, domains, user accounts, and observed behavior patterns.
5. If any commands (especially PowerShell) are present, display them in preformatted text on a new line using triple backticks (```command```), followed by a one-sentence explanation of what the command does.
6. Maintain a concise, professional tone without unnecessary “fluff,” such as lengthy background explanations or details on log sources.
7. Avoid ending with a one-sentence recap of all findings. This entire section is the summary.
8. Optionally conclude with: “We recommend that you investigate this activity further, as the activity appears to X.”
9. The text should read like a single cohesive summary paragraph, not a list or procedural walkthrough. *

## Key Details:
*Write the "Key Details" section for an MDR SOC report.
Follow these instructions exactly:
1. Present each item on a separate line — no bullet points, numbering, or paragraph text.
2. Each line should follow this consistent format:  
   Label: Value (e.g. Host: WIN-123)
3. Use short, descriptive labels like `User:`, `Host:`, `Source IP:`, `Destination IP:`, `Domain:`, `File Path:`, `Command Executed:`, `Process Chain:`, etc.
4. Include ONLY the most relevant technical information from the tagged logs such as:  
   - Impacted users, hosts, or systems  
   - IP addresses (source/destination)  
   - Domains, URLs, or file paths involved  
   - PowerShell or script commands executed  
   - Process chains observed  
   - Event IDs
   - Any other clear indicators of compromise (IOCs) or suspicious activity
If multiple values exist for a single item type (such as several domains or IP addresses), you may use bullet points directly under that label to list them.
5. Do not include where the data originated in this section (e.g., Defender, Sentinel, SIEM, etc.). Only the data itself.
6. Keep entries factual and concise — no sentences, commentary, or explanations unless it’s a short clarification (e.g., “Encoded PowerShell command used for payload retrieval”).
7. Maintain a consistent, clean layout with one item per line. Avoid extra spacing or markdown formatting beyond basic colons and line breaks.*

## Consequence:
*Describe the potential or confirmed impact of the incident, such as data exposure, privilege escalation, lateral movement, or system compromise. No not use bullet-points here, write as a text.
This section should not include any containment suggestions.*

# CONTAINMENT
* This section should exclusively focus on immediate remediation actions, both that the SOC has done, and that the customer needs to do themselves*

## Executed Remediation Actions:
* Start this section with the following: "The following containment and eradication actions has been performed by our SOC:"
1. Follow this up with a bullet point list of concrete immediate containment and eradication actions that the Tier 1 SOC analyst must do/has done in order to contain, remediate or resolve the identified threat.
2. The immediate actions that the Tier 1 analyst can do is based on the customer contract "mdr_contract_type", and the playbook content.
3. Be very concrete when describing what has been done. 
4. Remember, you are only an AI-assistant, and you can propose natural steps that the analyst should take, however what they actually do is inevitably up to them.
5. Be brief in wording: (e.g. Isolated the host, due to X) is good enough. 
6. If no specific actions can be performed by the SOC (e.g., for EDR customers), you may write: "No actions applicable by the MDR SOC due to customer contract."
*

## Recommended Remediation Actions:
* Start this section with the following: "Our SOC recommends that you do the following containment actions:"
1. Use bullet points to list out concrete immediate containment and eradication actions that the customer must do (that the SOC could not do), in order to contain, remediate or resolve the identified threat.  
2. This should only focus on high level, immediate actions. 
3. Do not come up with any points regarding strategy, governance and compliance, or similar, here. That is not the scope for these reports. Just concrete actions that needs to be taken.  
4. If all remediation actions have been completed by the MDR SOC and the report is intended solely to inform the customer (e.g., for XDR customers), you may write: "All remediation actions have been completed by the MDR SOC."
*
"""

    ########################################################################################################################

    with open("outputs/prompt_in.txt", "w", encoding="utf-8") as f:
        f.write(prompt)

    # --- Call ChatGPT ---; seed 42 ensures more consistency of output.
    response = openai.chat.completions.create(
        model="gpt-5",
        messages=[{"role": "user", "content": prompt}],
        top_p=1,
        seed=42
    )

    return response.choices[0].message.content

app = Flask(__name__)


@app.post("/llm")
def llm_endpoint():
    os.makedirs("outputs", exist_ok=True)
    print("got a request for /llm endpoint\n waiting for a response")
    try:
        payload = request.get_json(force=True) or {}
    except Exception as e:
        return Response(f"bad json: {e}\n", status=400, mimetype="text/plain")
    print("Request I retrived was", payload)

    siem_alert_dict = payload.get("siem_alert") or []
    if isinstance(siem_alert_dict, dict) and "raw" in siem_alert_dict:
        siem_alert_item = siem_alert_dict.get("raw") or []
    elif isinstance(siem_alert_dict, list):
        siem_alert_item = siem_alert_dict
    else:
        siem_alert_item = []

    def find_data_in_siem_alert(key):
        for it in siem_alert_item:
            if isinstance(it, dict) and key in it:
                return it[key]
        return None

    # Keep your original fallbacks, but look inside siem_alert if missing
    user_query = payload.get("type") or find_data_in_siem_alert("type") or ""
    customer = payload.get("Customer") or find_data_in_siem_alert("Customer") or {}
    log_lines = payload.get("log_lines") or []
    siem_alert = payload.get("siem_alert") or {}
    initial_analysis = payload.get("initial_analysis") or ""

    print("user_query", user_query)
    print("customer", customer)
    print("log_lines", log_lines)
    print("siem_alert", siem_alert)
    print("initial_analysis", initial_analysis)

    answer = rag_chat(str(user_query), initial_analysis, str(customer), log_lines, siem_alert)
    with open("outputs/response.txt", "w", encoding="utf-8") as f:
        f.write(answer)
    print("we got the answer: ", answer)
    return Response(answer, mimetype="text/plain")


app.run(host="0.0.0.0", port=8000, debug=True)
