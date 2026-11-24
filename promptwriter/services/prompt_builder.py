from promptwriter.services.lora import (
    build_image_lora_instructions,
    build_lora_instructions,
)

VISION_DEFAULT_USER_PROMPT = (
    "Generate the prompt for the provided image, "
    "following the system instructions."
)


def assemble_text_request(prompt_path, lora_profile_name, lora_profiles, camera, user_idea):
    if not prompt_path.is_file():
        raise ValueError("Select a valid target model before generating.")

    system_parts = [prompt_path.read_text(encoding="utf-8").strip()]
    lora_instructions = build_lora_instructions(lora_profile_name, lora_profiles)
    if lora_instructions:
        system_parts.append(lora_instructions)

    if camera != "None / Auto":
        system_parts.append(
            f"The image is shot on {camera}. "
            "Include relevant photography terms."
        )
    return {
        "system": "\n\n".join(part for part in system_parts if part),
        "user": f"User's rough idea:\n{user_idea}".strip(),
    }


def assemble_image_request(
    prompt_path, lora_profile_name, lora_profiles, additional_context
):
    if not prompt_path.is_file():
        raise ValueError("Select a valid target model before generating.")

    system_parts = [prompt_path.read_text(encoding="utf-8").strip()]
    lora_instructions = build_image_lora_instructions(
        lora_profile_name, lora_profiles
    )
    if lora_instructions:
        system_parts.append(lora_instructions)
    context = (additional_context or "").strip()
    user_text = VISION_DEFAULT_USER_PROMPT
    if context:
        user_text = (
            f"{VISION_DEFAULT_USER_PROMPT}\n\n"
            f"Additional context and instructions:\n{context}"
        )
    return {
        "system": "\n\n".join(part for part in system_parts if part),
        "user": user_text,
    }
