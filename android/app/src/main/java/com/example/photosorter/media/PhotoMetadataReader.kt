package com.example.photosorter.media

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import com.example.photosorter.model.PhotoItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.IOException

/** Reads only metadata; the original image bytes are streamed later when copied. */
class PhotoMetadataReader(context: Context) {
    private val appContext = context.applicationContext

    suspend fun read(uri: Uri): PhotoItem = withContext(Dispatchers.IO) {
        val resolver = appContext.contentResolver
        var displayName: String? = null
        resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val column = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (column >= 0) displayName = cursor.getString(column)
            }
        }
        val nameExtension = displayName?.substringAfterLast('.', "")?.lowercase().orEmpty()
        val mimeType = resolver.getType(uri)?.lowercase()
            ?: MimeTypeMap.getSingleton().getMimeTypeFromExtension(nameExtension)
            ?: when (nameExtension) {
                "heic" -> "image/heic"
                "heif" -> "image/heif"
                else -> null
            }
            ?: throw IOException("선택한 사진의 형식을 확인할 수 없습니다")
        if (!mimeType.startsWith("image/") || mimeType == "image/*") {
            throw IOException("지원되는 사진 형식이 아닙니다")
        }
        val extension = MimeTypeMap.getSingleton().getExtensionFromMimeType(mimeType)
            ?: when (mimeType) {
                "image/heic" -> "heic"
                "image/heif" -> "heif"
                "image/jpeg", "image/jpg" -> "jpg"
                "image/webp" -> "webp"
                else -> "img"
            }
        val safeName = safePhotoFileName(displayName, extension)
        PhotoItem(
            sourceUri = uri.toString(),
            displayName = safeName,
            mimeType = if (mimeType == "image/jpg") "image/jpeg" else mimeType,
        )
    }
}

/** Keep provider supplied names out of directory handling and within common filesystem limits. */
internal fun safePhotoFileName(rawName: String?, fallbackExtension: String): String {
    var name = rawName.orEmpty().substringAfterLast('/').substringAfterLast('\\')
        .map { char -> if (char.code < 32 || char.code == 127 || char in "<>:\"/\\|?*") '_' else char }
        .joinToString("")
        .trim(' ', '.')
    if (name.isBlank()) name = "photo_${System.currentTimeMillis()}"
    val dot = name.lastIndexOf('.')
    // The provider's suffix may be wrong. Match the actual MIME type so gallery scanners
    // recognize a byte-for-byte copy on Android 8–9 as well as newer MediaStore versions.
    val extension = "." + fallbackExtension.lowercase()
        .filter { it in 'a'..'z' || it in '0'..'9' }
        .take(12).ifBlank { "img" }
    var stem = (if (dot > 0) name.substring(0, dot) else name).ifBlank { "photo" }.take(100)
    while (stem.toByteArray(Charsets.UTF_8).size + extension.toByteArray(Charsets.UTF_8).size > 220) {
        stem = stem.dropLast(1)
    }
    return stem + extension
}
