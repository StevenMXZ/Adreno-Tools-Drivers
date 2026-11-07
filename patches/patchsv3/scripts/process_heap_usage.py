from mesa_edit import replace

DEVICE = 'src/freedreno/vulkan/tu_device.cc'

replace(
    DEVICE,
    'static inline VkDeviceSize\ntu_get_budget_memory(',
    """static uint64_t tu_process_heap_used;

static inline VkDeviceSize
tu_get_budget_memory(""",
    'process-wide heap usage counter',
)

replace(
    DEVICE,
    'memory_budget_props->heapUsage[0] = p_atomic_read(&physical_device->heap.used);',
    'memory_budget_props->heapUsage[0] = p_atomic_read(&tu_process_heap_used);',
    'memory budget reports the process-wide usage',
)

replace(
    DEVICE,
    """                       "Out of heap memory");
   }
   return VK_SUCCESS;
}""",
    """                       "Out of heap memory");
   }
   p_atomic_add(&tu_process_heap_used, bo->size);
   return VK_SUCCESS;
}""",
    'allocations counted process-wide',
)

replace(
    DEVICE,
    '      p_atomic_add(&device->physical_device->heap.used, -mem->bo->size);\n',
    '      p_atomic_add(&device->physical_device->heap.used, -mem->bo->size);\n'
    '      p_atomic_add(&tu_process_heap_used, -mem->bo->size);\n',
    'frees counted process-wide',
)
