package com.example.photosorter.media

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AlbumPathTest {
    @Test
    fun acceptsOnlyLocalSharedImageAreas() {
        assertEquals("Pictures/가족/", normalizeImageAlbumPath("Pictures/가족/"))
        assertEquals("DCIM/Camera/", normalizeImageAlbumPath("DCIM/Camera"))
        assertNull(normalizeImageAlbumPath("Downloads/가족/"))
        assertNull(normalizeImageAlbumPath("/Pictures/가족/"))
        assertNull(normalizeImageAlbumPath("Pictures/../Other/"))
        assertNull(normalizeImageAlbumPath("Pictures\\가족\\"))
    }
}
