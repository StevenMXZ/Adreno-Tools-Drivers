#!/usr/bin/env python3
"""Restore the Gen8 IR3 profile helpers and A8xx concurrent-binning default."""
from mesa_edit import replace

replace("src/freedreno/ir3/ir3_compiler.c",
        "const char *ir3_shader_override_path = NULL;\n\n",
        "const char *ir3_shader_override_path = NULL;\n\nstruct ir3_gpu_profile\nir3_get_gpu_profile(uint32_t chip_id)\n{\n    switch (chip_id) {\n    case 0x44010000: /* Adreno 810 */\n        return (struct ir3_gpu_profile){90, 4, 4, false};\n    case 0x44030000: /* Adreno 825 */\n        return (struct ir3_gpu_profile){85, 8, 8, true};\n    case 0x44030A20: /* Adreno 829 */\n        return (struct ir3_gpu_profile){80, 10, 8, true};\n    case 0x44050001: /* Adreno 830 */\n        return (struct ir3_gpu_profile){75, 16, 12, true};\n    case 0x43050A31: /* Adreno 830 variant */\n        return (struct ir3_gpu_profile){75, 16, 12, true};\n    case 0x43050A32: /* Adreno 840 */\n        return (struct ir3_gpu_profile){70, 20, 16, true};\n    default:\n        return (struct ir3_gpu_profile){85, 8, 8, false};\n    }\n}\n\nuint32_t\nir3_effective_reg_size(struct ir3_compiler *compiler)\n{\n    struct ir3_gpu_profile profile = ir3_get_gpu_profile(compiler->dev_id->chip_id);\n    return compiler->reg_size_vec4 * profile.reg_efficiency / 100;\n}\n\n",
        "Gen8 IR3 profile table")

replace("src/freedreno/ir3/ir3_compiler.h",
        "struct ir3_compiler {\n",
        "struct ir3_gpu_profile {\n    uint32_t reg_efficiency;\n    uint32_t max_sy_inflight;\n    uint32_t max_ss_inflight;\n    bool force_double_threadsize;\n};\n\nstruct ir3_compiler {\n",
        "Gen8 IR3 profile structure")

replace("src/freedreno/ir3/ir3_compiler.h",
        "\nENDC;\n",
        "\n/* ========== A8XX HELPER FUNCTIONS ========== */\n\nstruct ir3_gpu_profile;\nstruct ir3_gpu_profile ir3_get_gpu_profile(uint32_t chip_id);\nuint32_t ir3_effective_reg_size(struct ir3_compiler *compiler);\n\nstatic inline bool\nir3_force_double_threadsize(struct ir3_compiler *compiler)\n{\n   if (compiler->gen >= 8) {\n      struct ir3_gpu_profile profile = ir3_get_gpu_profile(compiler->dev_id->chip_id);\n      return profile.force_double_threadsize;\n   }\n   return compiler->info->props.supports_double_threadsize;\n}\n\n/* Helper function to check if A8XX should use aggressive const limits */\nstatic inline bool\nir3_use_aggressive_const_limits(struct ir3_compiler *compiler)\n{\n   return compiler->gen >= 8;\n}\n\n/* Helper function to get optimal delay slots for current gen */\nstatic inline unsigned\nir3_get_alu_to_alu_delay(struct ir3_compiler *compiler)\n{\n   if (compiler->gen >= 8)\n      return 1;\n   if (compiler->gen >= 7)\n      return 2;\n   return 3;\n}\n\nstatic inline unsigned\nir3_get_non_alu_delay(struct ir3_compiler *compiler)\n{\n   if (compiler->gen >= 8)\n      return 4;\n   if (compiler->gen >= 7)\n      return 5;\n   return 6;\n}\n\n/* ========== END A8XX HELPER FUNCTIONS ========== */\n\nENDC;\n",
        "Gen8 IR3 profile helpers")

replace("src/freedreno/vulkan/tu_cmd_buffer.cc",
        "   if (tu7_cb_disable_reason(disable_cb, cmd, \"disable_cb\") ||\n",
        "   if (tu7_cb_disable_reason(\n          cmd->device->physical_device->info->chip == A8XX &&\n          !TU_DEBUG(FORCE_CONCURRENT_BINNING), cmd, \"A8xx concurrent binning disabled\") ||\n       tu7_cb_disable_reason(disable_cb, cmd, \"disable_cb\") ||\n",
        "A8xx concurrent binning default")

replace("src/freedreno/vulkan/tu_cmd_buffer.cc",
        "       cmd_buffer->device->instance->drirc.perf.allow_concurrent_binning) {\n",
        "       (CHIP < A8XX || TU_DEBUG(FORCE_CONCURRENT_BINNING)) &&\n       cmd_buffer->device->instance->drirc.perf.allow_concurrent_binning) {\n",
        "A8xx concurrent binning barrier guard")
