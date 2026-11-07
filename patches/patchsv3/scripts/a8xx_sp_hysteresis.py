from mesa_edit import replace

replace(
    'src/freedreno/vulkan/tu_cmd_buffer.cc',
    '   if (CHIP >= A8XX)\n'
    '      tu_cs_emit_regs(cs, SP_ALPHA_TEST_CNTL(CHIP));\n',
    '   if (CHIP >= A8XX) {\n'
    '      tu_cs_emit_regs(cs, SP_ALPHA_TEST_CNTL(CHIP));\n'
    '      tu_cs_emit_regs(cs, SP_PS_HYSTERESIS(CHIP, .dword = 0x00000c00));\n'
    '      tu_cs_emit_regs(cs, SP_VS_HYSTERESIS(CHIP, .dword = 0x00000400));\n'
    '   }\n',
    'A8XX VS / PS hysteresis in the preamble',
)
