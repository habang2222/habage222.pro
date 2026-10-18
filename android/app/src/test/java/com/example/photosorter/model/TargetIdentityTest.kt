package com.example.photosorter.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class TargetIdentityTest {
    @Test
    fun recreatedMappingForSameFolderRetainsCopyIdentity() {
        val original = AlbumMapping("old-id", "민지", "민지", null,
            "external_primary", "Pictures/민지/", true)
        val recreated = original.copy(id = "new-id", inputName = "별칭")
        assertEquals(original.targetKey(), recreated.targetKey())
        assertEquals(original.targetKey(), original.copy(volumeName = "primary").targetKey())
        assertNotEquals(original.targetKey(), original.copy(relativePath = "Pictures/다른앨범/").targetKey())
    }
}
