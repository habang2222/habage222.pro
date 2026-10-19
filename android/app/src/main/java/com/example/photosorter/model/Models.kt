package com.example.photosorter.model

/** A registered physical gallery album; inputName is retained for saved-state migration. */
data class AlbumMapping(
    val id: String,
    val inputName: String,
    val albumDisplayName: String,
    val bucketId: String?,
    val volumeName: String,
    val relativePath: String,
    val isAppCreated: Boolean,
)

/** Stable physical destination identity, including after a mapping is removed and recreated. */
fun targetKey(volumeName: String, relativePath: String): String {
    val volume = when (volumeName) {
        "primary", "external" -> "external_primary"
        else -> volumeName
    }
    return "$volume\u0000${relativePath.trimEnd('/')}/"
}

fun AlbumMapping.targetKey(): String = targetKey(volumeName, relativePath)

/** A group of photos visible through MediaStore, which may or may not accept new photos. */
data class DeviceAlbum(
    val id: String,
    val displayName: String,
    val count: Int,
    val coverUri: String,
    val bucketId: String?,
    val volumeName: String,
    val relativePath: String?,
    val writable: Boolean,
)

enum class PhotoStatus { PENDING, COMPLETED, SKIPPED, ERROR }

data class PhotoItem(
    val sourceUri: String,
    val displayName: String,
    val mimeType: String,
    val status: PhotoStatus = PhotoStatus.PENDING,
    val inputNames: List<String> = emptyList(),
    /** Physical albums chosen for this photo. These survive alias edits and retries. */
    val selectedTargets: Set<String> = emptySet(),
    /** Physical destination keys already copied successfully, including earlier sessions. */
    val completedTargets: Set<String> = emptySet(),
    /** Destination keys newly copied during this selection/session. */
    val newCopies: Set<String> = emptySet(),
    val errorMessage: String? = null,
)

data class SorterData(
    val mappings: List<AlbumMapping> = emptyList(),
    val items: List<PhotoItem> = emptyList(),
    val currentIndex: Int = 0,
    /** Best-effort duplicate protection when the same picker URI is selected in another session. */
    val copyLedger: Map<String, Set<String>> = emptyMap(),
)
