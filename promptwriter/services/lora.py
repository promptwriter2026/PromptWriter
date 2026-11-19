def lora_profile_value(profile, key):
    legacy_keys = {
        "name": "Name",
        "trigger_word": "Trigger Word",
        "description": "Description",
    }
    value = profile.get(key, profile.get(legacy_keys[key], ""))
    return value.strip() if isinstance(value, str) else ""


def find_lora_profile(profile_name, profiles):
    return next(
        (
            item
            for item in profiles
            if isinstance(item, dict)
            and lora_profile_value(item, "name") == profile_name
        ),
        None,
    )


def build_lora_instructions(profile_name, profiles):
    if profile_name == "None":
        return ""
    profile = find_lora_profile(profile_name, profiles)
    if profile is None:
        raise ValueError(f"LoRA profile not found: {profile_name}")
    trigger_words = lora_profile_value(profile, "trigger_word")
    description = lora_profile_value(profile, "description")
    if not trigger_words or not description:
        raise ValueError(
            f"LoRA profile '{profile_name}' must include trigger words and a description."
        )
    return (
        "CHARACTER IDENTITY & STYLING RULES:\n"
        "1. CORE IDENTITY LOCK: You MUST replace the subject's core physical "
        "identity (ethnicity, age, facial features, base body type) with this "
        f"exact LoRA profile: {description}. If the user's input describes a "
        "different core identity (e.g., 'East Asian'), ignore the input and use "
        "the LoRA profile.\n"
        "2. DYNAMIC STYLING: Hair color, hairstyle, makeup, and clothing are "
        "mutable. If the user's input explicitly specifies a styling choice "
        "(e.g., 'pink hair', 'short bob', 'black hair'), apply that specific "
        "style to the character. If no hair/styling is mentioned in the input, "
        f"default to the traits in the LoRA profile: {description}.\n"
        f"3. TRIGGER: You MUST place the exact trigger words '{trigger_words}' "
        "at the VERY BEGINNING of your final prompt."
    )


def build_image_lora_instructions(profile_name, profiles):
    if profile_name == "None":
        return ""
    profile = find_lora_profile(profile_name, profiles)
    if profile is None:
        raise ValueError(f"LoRA profile not found: {profile_name}")
    trigger_words = lora_profile_value(profile, "trigger_word")
    description = lora_profile_value(profile, "description")
    if not trigger_words or not description:
        raise ValueError(
            f"LoRA profile '{profile_name}' must include trigger words and a description."
        )
    return (
        "CHARACTER REPLACEMENT RULE:\n"
        "The user wants to replace the main subject in the provided image with "
        "their custom character. When describing the person in the image, you "
        "MUST IGNORE their original physical appearance (age, gender, facial "
        "features, hair, body type) and REPLACE it completely with this profile: "
        f"{description}\n"
        "However, you MUST STRICTLY PRESERVE the original subject's exact pose, "
        "clothing, actions, and expression. Keep the entire background, "
        "environment, lighting, and camera style exactly as seen in the original "
        "image.\n"
        f"You MUST place the exact trigger words '{trigger_words}' at the VERY "
        "BEGINNING of your final generated prompt."
    )


def enforce_lora_trigger_prefix(generated_prompt, trigger_words):
    prompt = generated_prompt.strip()
    if trigger_words and not prompt.casefold().startswith(trigger_words.casefold()):
        return f"{trigger_words} {prompt}"
    return prompt
