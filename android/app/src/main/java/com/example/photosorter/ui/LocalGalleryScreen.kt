package com.example.photosorter.ui

import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.example.photosorter.viewmodel.LocalGalleryUiState

/** Shows photos from the device's MediaStore without opening the system photo picker. */
@Composable
fun LocalGalleryScreen(
    state: LocalGalleryUiState,
    access: PhotoAccess,
    onOpenAlbum: (String) -> Unit,
    onBackToAlbums: () -> Unit,
    onTogglePhoto: (String) -> Unit,
    onToggleShowProcessed: () -> Unit,
    onLoadMore: () -> Unit,
    onConfirmSelection: () -> Unit,
    onReviewPermission: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val currentAlbum = state.albums.firstOrNull { it.key == state.currentAlbumKey }

    Column(Modifier.fillMaxSize()) {
        if (access != PhotoAccess.FULL) {
            Surface(
                color = MaterialTheme.colorScheme.secondaryContainer,
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Column(Modifier.padding(12.dp)) {
                    Text(
                        if (access == PhotoAccess.PARTIAL)
                            "허용한 사진만 보입니다. 전체 앨범을 보려면 사진 접근 범위를 변경하세요."
                        else "사진을 보려면 사진 접근 권한이 필요합니다.",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton(onClick = onReviewPermission) { Text("사진 접근 범위 변경") }
                        TextButton(onClick = onOpenSettings) { Text("앱 설정") }
                    }
                }
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (state.currentAlbumKey != null) {
                TextButton(onClick = onBackToAlbums) { Text("‹ 앨범") }
                Text(
                    text = currentAlbum?.displayName ?: "앨범",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f).padding(start = 8.dp),
                )
            } else {
                Text(
                    "휴대전화 앨범",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
            }
            FilterChip(
                selected = state.showProcessed,
                onClick = onToggleShowProcessed,
                label = { Text("분류한 사진 보기") },
            )
        }

        if (!state.showProcessed) {
            Text(
                "앱이 인식한 분류 사진과 복사본은 이 화면에서 숨깁니다. 폴더의 실제 파일은 그대로입니다.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 2.dp),
            )
        }
        if (state.selectedUris.isNotEmpty()) {
            Text(
                "표시를 바꾸면 사진 선택이 초기화됩니다.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 2.dp),
            )
        }
        if (state.error != null) {
            Text(
                state.error,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            )
        }

        when {
            state.loading && state.albums.isEmpty() -> LoadingGallery(Modifier.weight(1f))
            state.currentAlbumKey == null -> {
                if (state.albums.isEmpty()) {
                    EmptyGallery(
                        if (access == PhotoAccess.DENIED) "사진 접근 권한을 허용해 주세요."
                        else "표시할 휴대전화 앨범이 없습니다.",
                        Modifier.weight(1f),
                    )
                } else {
                    LazyVerticalGrid(
                        columns = GridCells.Adaptive(minSize = 145.dp),
                        modifier = Modifier.fillMaxWidth().weight(1f),
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        items(state.albums, key = { it.key }) { album ->
                            Card(
                                modifier = Modifier.fillMaxWidth().clickable {
                                    onOpenAlbum(album.key)
                                },
                            ) {
                                Column {
                                    Box(
                                        modifier = Modifier.fillMaxWidth().aspectRatio(1f)
                                            .background(MaterialTheme.colorScheme.surfaceVariant),
                                        contentAlignment = Alignment.Center,
                                    ) {
                                        Text("사진 없음", style = MaterialTheme.typography.bodySmall)
                                        AsyncImage(
                                            model = album.coverUri.takeIf(String::isNotBlank)?.let(Uri::parse),
                                            contentDescription = "${album.displayName} 앨범 대표 사진",
                                            modifier = Modifier.fillMaxSize(),
                                            contentScale = ContentScale.Crop,
                                        )
                                    }
                                    Column(Modifier.padding(10.dp)) {
                                        Text(
                                            album.displayName,
                                            style = MaterialTheme.typography.titleSmall,
                                            maxLines = 2,
                                            overflow = TextOverflow.Ellipsis,
                                        )
                                        Text(
                                            "${album.count}장",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
            state.loading && state.photos.isEmpty() -> LoadingGallery(Modifier.weight(1f))
            else -> {
                if (state.photos.isEmpty()) {
                    EmptyGallery(
                        if (state.showProcessed) "이 앨범에 표시할 사진이 없습니다."
                        else "이 앨범에 아직 분류하지 않은 사진이 없습니다.",
                        Modifier.weight(1f),
                    )
                } else {
                    LazyVerticalGrid(
                        columns = GridCells.Fixed(3),
                        modifier = Modifier.fillMaxWidth().weight(1f),
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(2.dp),
                        horizontalArrangement = Arrangement.spacedBy(2.dp),
                        verticalArrangement = Arrangement.spacedBy(2.dp),
                    ) {
                        items(state.photos, key = { it.uri }) { photo ->
                            val isSelected = photo.uri in state.selectedUris
                            Box(
                                modifier = Modifier.fillMaxWidth().aspectRatio(1f)
                                    .clip(RoundedCornerShape(2.dp))
                                    .background(MaterialTheme.colorScheme.surfaceVariant)
                                    .clickable { onTogglePhoto(photo.uri) }
                                    .semantics {
                                        selected = isSelected
                                        contentDescription = "${photo.displayName}, " +
                                            if (isSelected) "선택됨" else "선택되지 않음"
                                    },
                            ) {
                                AsyncImage(
                                    model = Uri.parse(photo.uri),
                                    contentDescription = null,
                                    modifier = Modifier.fillMaxSize(),
                                    contentScale = ContentScale.Crop,
                                )
                                if (isSelected) {
                                    Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.36f)))
                                }
                                if (photo.isProcessed) {
                                    Surface(
                                        color = Color.Black.copy(alpha = 0.68f),
                                        shape = RoundedCornerShape(4.dp),
                                        modifier = Modifier.align(Alignment.BottomStart).padding(5.dp),
                                    ) {
                                        Text(
                                            "분류본",
                                            style = MaterialTheme.typography.labelSmall,
                                            color = Color.White,
                                            modifier = Modifier.padding(horizontal = 5.dp, vertical = 2.dp),
                                        )
                                    }
                                }
                                Box(
                                    modifier = Modifier.align(Alignment.TopEnd).padding(6.dp)
                                        .size(25.dp).clip(CircleShape)
                                        .background(
                                            if (isSelected) MaterialTheme.colorScheme.primary
                                            else Color.Black.copy(alpha = 0.45f)
                                        ),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Text(
                                        if (isSelected) "✓" else "",
                                        color = Color.White,
                                        style = MaterialTheme.typography.labelMedium,
                                    )
                                }
                            }
                        }
                    }
                }
                if (state.hasMore || state.loadingMore) {
                    Box(
                        modifier = Modifier.fillMaxWidth().padding(8.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        if (state.loadingMore) CircularProgressIndicator(Modifier.size(24.dp))
                        else OutlinedButton(onClick = onLoadMore) { Text("사진 더 보기") }
                    }
                }
            }
        }

        if (state.selectedUris.isNotEmpty()) {
            Surface(shadowElevation = 8.dp) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(12.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "${state.selectedUris.size}장 선택",
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Spacer(Modifier.weight(1f))
                    Button(onClick = onConfirmSelection) { Text("선택한 사진 분류하기") }
                }
            }
        }
    }
}

@Composable
private fun LoadingGallery(modifier: Modifier) {
    Box(modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
private fun EmptyGallery(message: String, modifier: Modifier) {
    Box(modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        Text(
            message,
            modifier = Modifier.padding(24.dp),
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
        )
    }
}
