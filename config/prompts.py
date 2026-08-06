JD_ANALYSIS_PROMPT = """
You are a senior technical recruiter with deep expertise in cloud infrastructure,
MLOps, and AI engineering. Analyze the following job description against the
candidate's profile and return a structured JSON response.

CANDIDATE PROFILE (JSON):
{cv_json}

JOB DESCRIPTION:
{jd_text}

Return ONLY valid JSON with this exact schema:
{{
  "fit_score": <float 0.0-1.0>,
  "matched_skills": [<list of matched skills>],
  "missing_skills": [<list of skills required but candidate lacks>],
  "role_level_match": <"junior"|"match"|"overqualified">,
  "salary_range_visible": <null or "$X-$Y">,
  "remote_friendly": <true|false>,
  "hiring_manager_signals": [<names or titles found in JD if any>],
  "company_growth_signals": [<funding, expansion, new product mentions>],
  "application_recommended": <true|false>,
  "rejection_reason": <null or "brief reason if not recommended">
}}
"""

PITCH_GENERATION_PROMPT = """
You are writing a direct outreach message from {candidate_name} to a hiring manager
at {company_name}. The goal is a concise, technical, and human message — NOT a
cover letter, NOT generic.

CANDIDATE PROFILE:
{cv_json}

JOB CONTEXT:
- Role: {job_title}
- Company growth signals: {growth_signals}
- Key matched skills: {matched_skills}

RECIPIENT:
- Name: {manager_name}
- Title: {manager_title}

RULES:
- Maximum 4 sentences. No fluff.
- Open with a specific observation about their company or role — not a compliment.
- Mention 1 concrete project from the candidate's profile that maps directly to
  their needs. Include the GitHub link if relevant.
- End with a single, low-friction ask (15-min call, not "please review my resume").
- Tone: peer-to-peer between engineers, not applicant-to-gatekeeper.
- Language: English.

Return ONLY the message text, no subject line, no JSON.
"""

CONNECTION_NOTE_TECHNICAL_PROMPT = """
Write a LinkedIn connection request note from {candidate_name} to {manager_first_name}.

HARD RULES:
- Maximum 198 characters total. Count every character carefully.
- Start with their first name, a space, em dash, a space (example: "Keith — ").
- Reference the specific job role and company in a natural way.
- Mention ONE concrete technical project or achievement — vary the angle, do not always use the same metric.
- End exactly with: "Thought it was worth connecting directly."
- No URLs, no phone numbers, no emojis, no subject line.
- Do NOT invent company statistics or facts not given in the context.
- English only. Peer-to-peer engineer tone, not applicant tone.

JOB CONTEXT:
- Role: {job_title}
- Company: {company_name}
- Key signals: {growth_signals}
- Matched skills: {matched_skills}

CANDIDATE KEY HIGHLIGHTS:
{cv_summary}

Return ONLY the note text. Nothing else.
"""

CONNECTION_NOTE_RECRUITER_PROMPT = """
Write a LinkedIn connection request note from {candidate_name} to {manager_first_name}, who works in talent acquisition or recruiting.

HARD RULES:
- Maximum 198 characters total. Count every character carefully.
- Start with their first name, a space, em dash, a space (example: "Janet — ").
- Mention you saw the role at the company and that you're actively looking.
- State your core identity in one phrase (Senior DevOps / Cloud Platform Engineer).
- End with a soft, low-friction close — not "do you have 15 minutes".
- No URLs, no phone numbers, no emojis.
- Do NOT invent facts.
- English only. Direct but warm tone.

JOB CONTEXT:
- Role: {job_title}
- Company: {company_name}
- Matched skills: {matched_skills}

CANDIDATE NAME: {candidate_name}

Return ONLY the note text. Nothing else.
"""

FORM_FIELD_MAPPING_PROMPT = """
You are filling out a job application form on behalf of {candidate_name}.
Map each form field to the correct value from the candidate's profile.

CANDIDATE PROFILE:
{cv_json}

FORM FIELDS DETECTED:
{form_fields}

Return ONLY valid JSON mapping field_id or field_label to the value to fill:
{{
  "<field_id_or_label>": "<value>",
  ...
}}

If a field cannot be answered from the profile, use null.
Never invent information not present in the profile.
"""
