package com.example.photosorter.media

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LocalPickerUriTest {
    @Test fun acceptsOnlyExactLocalPickerUriForCurrentUser() {
        assertEquals(
            1000004877L,
            localPickerImageId(
                "content://media/picker/0/com.android.providers.media.photopicker/media/1000004877",
                0,
            ),
        )
        assertEquals(
            72L,
            localPickerImageId(
                "content://media/picker_get_content/10/com.android.providers.media.photopicker/media/72",
                10,
            ),
        )
        assertNull(localPickerImageId(
            "content://media/picker/10/com.android.providers.media.photopicker/media/72", 0
        ))
    }

    @Test fun neverMapsCloudOrMalformedPickerUriToLocalId() {
        assertNull(localPickerImageId(
            "content://media/picker/0/com.google.android.apps.photos.contentprovider/media/72", 0
        ))
        assertNull(localPickerImageId(
            "content://media/picker/0/com.android.providers.media.photopicker/media/72?x=1", 0
        ))
        assertNull(localPickerImageId(
            "content://media/picker/0/com.android.providers.media.photopicker/media/0", 0
        ))
        assertNull(localPickerImageId(
            "content://media/picker/0/com.android.providers.media.photopicker/media/not-an-id", 0
        ))
    }
}
