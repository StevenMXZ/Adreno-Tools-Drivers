from mesa_edit import replace

replace(
    'src/freedreno/common/freedreno_devices.py',
    '        [A6XXRegs.REG_A8XX_RB_RESOLVE_CNTL_5, 0x00000001],\n',
    '        [A6XXRegs.REG_A8XX_RB_RESOLVE_CR_CNTL, 0x00000001],\n'
    '        [A6XXRegs.REG_A8XX_RB_RESOLVE_CNTL_5, 0x00000001],\n',
    'A8XX RB_RESOLVE_CR_CNTL in the preamble',
)
