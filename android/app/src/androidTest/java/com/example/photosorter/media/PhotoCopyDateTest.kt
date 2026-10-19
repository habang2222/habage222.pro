package com.example.photosorter.media

import android.content.ContentValues
import android.graphics.Bitmap
import android.net.Uri
import android.provider.MediaStore
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.example.photosorter.model.AlbumMapping
import com.example.photosorter.model.PhotoItem
import java.io.File
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PhotoCopyDateTest {
    @Test
    fun copiedImageKeepsSourceGalleryDateAndBytes() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val resolver = context.contentResolver
        val collection = MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        val sourcePath = "Pictures/PhotoSorterDateTest_${UUID.randomUUID()}/"
        val destinationPath = "Pictures/PhotoSorterDateTest_${UUID.randomUUID()}/"
        val source = resolver.insert(collection, ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, "date-test.png")
            put(MediaStore.MediaColumns.MIME_TYPE, "image/png")
            put(MediaStore.MediaColumns.RELATIVE_PATH, sourcePath)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }) ?: error("Could not create test source")
        var destination: Uri? = null
        try {
            resolver.openOutputStream(source, "w")!!.use { output ->
                val bitmap = Bitmap.createBitmap(2, 2, Bitmap.Config.ARGB_8888)
                try {
                    assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, output))
                } finally {
                    bitmap.recycle()
                }
            }
            val originalDateMillis = 1_577_836_800_000L // 2020-01-01 UTC
            assertTrue(File(mediaPath(source)).setLastModified(originalDateMillis))
            assertEquals(1, resolver.update(source, ContentValues().apply {
                put(MediaStore.MediaColumns.IS_PENDING, 0)
            }, null, null))
            val sourceModified = dateModified(source)
            assertEquals(originalDateMillis / 1000, sourceModified)

            destination = PhotoCopyManager(context).copy(
                PhotoItem(source.toString(), "date-test.png", "image/png"),
                AlbumMapping(
                    id = UUID.randomUUID().toString(),
                    inputName = "test",
                    albumDisplayName = "test",
                    bucketId = null,
                    volumeName = MediaStore.VOLUME_EXTERNAL_PRIMARY,
                    relativePath = destinationPath,
                    isAppCreated = true,
                ),
            )
            assertEquals(sourceModified, dateModified(destination))
            val sourceBytes = resolver.openInputStream(source)!!.use { it.readBytes() }
            val destinationBytes = resolver.openInputStream(destination)!!.use { it.readBytes() }
            assertArrayEquals(sourceBytes, destinationBytes)
        } finally {
            destination?.let { resolver.delete(it, null, null) }
            resolver.delete(source, null, null)
        }
    }

    private fun mediaPath(uri: Uri): String {
        val resolver = InstrumentationRegistry.getInstrumentation().targetContext.contentResolver
        return resolver.query(uri, arrayOf(MediaStore.MediaColumns.DATA), null, null, null)!!.use {
            assertTrue(it.moveToFirst())
            it.getString(it.getColumnIndexOrThrow(MediaStore.MediaColumns.DATA))
        }
    }

    private fun dateModified(uri: Uri): Long {
        val resolver = InstrumentationRegistry.getInstrumentation().targetContext.contentResolver
        return resolver.query(uri, arrayOf(MediaStore.MediaColumns.DATE_MODIFIED), null, null, null)!!.use {
            assertTrue(it.moveToFirst())
            it.getLong(it.getColumnIndexOrThrow(MediaStore.MediaColumns.DATE_MODIFIED))
        }
    }
}
