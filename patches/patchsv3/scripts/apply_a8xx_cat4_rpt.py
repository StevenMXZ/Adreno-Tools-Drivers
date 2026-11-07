from mesa_edit import replace

replace(
    'src/freedreno/ir3/ir3.c',
    '   case 4:\n'
    '      return opc != OPC_RCP;\n',
    '   case 4:\n'
    '      if (compiler->dev_id->chip_id == UINT64_C(0x44041430) ||\n'
    '          compiler->dev_id->chip_id == UINT64_C(0x44051431))\n'
    '         return false;\n'
    '      return opc != OPC_RCP;\n',
    'no category-4 repeat on A845 / A850',
)
