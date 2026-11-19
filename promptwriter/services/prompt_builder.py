from promptwriter.services.lora import (
    build_image_lora_instructions,
    build_lora_instructions,
)


def assemble_text_request(prompt_path, lora_profile_name, lora_profiles, camera, user_idea):
    if not prompt_path.is_file():
        raise ValueError("Select a valid target model before generating.")

    instruction_parts = [prompt_path.read_text(encoding="utf-8").strip()]
    lora_instructions = build_lora_instructions(lora_profile_name, lora_profiles)
    if lora_instructions:
        instruction_parts.append(lora_instructions)

    if camera != "None / Auto":
        instruction_parts.append(
            f"The image is shot on {camera}. "
            "Include relevant photography terms."
        )
    instruction_parts.append(f"User's rough idea:\n{user_idea}")
    return "\n\n".join(part for part in instruction_parts if part)


def assemble_image_request(
    prompt_path, lora_profile_name, lora_profiles, additional_context
):
    if not prompt_path.is_file():
        raise ValueError("Select a valid target model before generating.")

    instruction_parts = [prompt_path.read_text(encoding="utf-8").strip()]
    lora_instructions = build_image_lora_instructions(
        lora_profile_name, lora_profiles
    )
    if lora_instructions:
        instruction_parts.append(lora_instructions)
    if additional_context:
        instruction_parts.append(
            f"Additional context and instructions:\n{additional_context}"
        )
    return "\n\n".join(part for part in instruction_parts if part)
