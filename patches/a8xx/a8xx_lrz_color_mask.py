from mesa_edit import replace

PIPELINE = 'src/freedreno/vulkan/tu_pipeline.cc'

replace(
    PIPELINE,
    '      MAX2(cb->attachment_count, 1) : cb->attachment_count;\n'
    '   return 8 + 5 * num_rts;\n',
    '      MAX2(cb->attachment_count, 1) : cb->attachment_count;\n'
    '   return 8 + (CHIP >= A8XX ? 2 : 0) + 5 * num_rts;\n',
    'blend state size with GRAS_LRZ_COLOR_COMP_MASK',
)
replace(
    PIPELINE,
    '   unsigned num_remapped_rts = 0;\n'
    '   for (unsigned i = 0; i < num_rts; i++) {\n',
    '   unsigned num_remapped_rts = 0;\n'
    '   uint32_t lrz_color_comp_mask = 0;\n'
    '   for (unsigned i = 0; i < num_rts; i++) {\n',
    'LRZ color component mask accumulator',
)
replace(
    PIPELINE,
    '      if ((cb->color_write_enables & (1u << i)) && i < cb->attachment_count) {\n'
    '         const enum a3xx_rb_blend_opcode color_op',
    '      if ((cb->color_write_enables & (1u << i)) && i < cb->attachment_count) {\n'
    '         if (CHIP >= A8XX && remapped_idx < 8)\n'
    '            lrz_color_comp_mask |= (att->write_mask & 0xf) << (remapped_idx * 4);\n'
    '         const enum a3xx_rb_blend_opcode color_op',
    'per-MRT write masks into the LRZ color component mask',
)
replace(
    PIPELINE,
    '   tu_cs_emit_regs(cs, A6XX_RB_PS_MRT_CNTL(.mrt = num_remapped_rts));\n'
    '}\n',
    '   tu_cs_emit_regs(cs, A6XX_RB_PS_MRT_CNTL(.mrt = num_remapped_rts));\n'
    '   if (CHIP >= A8XX)\n'
    '      tu_cs_emit_regs(cs, GRAS_LRZ_COLOR_COMP_MASK(CHIP, .dword = lrz_color_comp_mask));\n'
    '}\n',
    'A8XX GRAS_LRZ_COLOR_COMP_MASK in the blend state',
)
