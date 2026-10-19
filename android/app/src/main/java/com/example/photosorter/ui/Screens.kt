package com.example.photosorter.ui

import android.net.Uri
import android.os.Build
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.example.photosorter.model.AlbumMapping
import com.example.photosorter.model.DeviceAlbum
import com.example.photosorter.model.PhotoStatus
import com.example.photosorter.model.targetKey
import com.example.photosorter.viewmodel.SorterUiState

enum class PhotoAccess { FULL, PARTIAL, DENIED }
enum class AppScreen { HOME, ALBUMS, CLASSIFY }

@Composable
fun PhotoSorterApp(
    state: SorterUiState,
    access: PhotoAccess,
    screen: AppScreen,
    showPermissionGate: Boolean,
    permissionWasRequested: Boolean,
    onConfirmPermission: () -> Unit,
    onReviewPermission: () -> Unit,
    onPermissionLater: () -> Unit,
    onOpenSettings: () -> Unit,
    onOpenGooglePhotos: () -> Unit,
    onNavigateHome: () -> Unit,
    onOpenAlbums: () -> Unit,
    onChoosePhotos: () -> Unit,
    onContinue: () -> Unit,
    onRegisterAlbum: (DeviceAlbum) -> Unit,
    onCreateAlbum: (String) -> Unit,
    onRemoveAlbum: (String) -> Unit,
    onSubmit: (Set<String>) -> Unit,
    onPrevious: () -> Unit,
    onResetSession: () -> Unit,
    onClearError: () -> Unit,
) {
    var showGooglePhotosHelp by rememberSaveable { mutableStateOf(false) }
    MaterialTheme {
        Surface(modifier = Modifier.fillMaxSize()) {
            if (showPermissionGate) {
                PermissionGate(
                    previouslyRequested = permissionWasRequested,
                    onConfirm = onConfirmPermission,
                    onLater = onPermissionLater,
                    onSettings = onOpenSettings,
                )
            } else {
                BackHandler(enabled = screen != AppScreen.HOME) { onNavigateHome() }
                Scaffold(
                    topBar = {
                        Header(
                            title = when (screen) {
                                AppScreen.HOME -> "등록된 앨범"
                                AppScreen.ALBUMS -> "앨범 선택"
                                AppScreen.CLASSIFY -> if (state.items.isNotEmpty())
                                    "${(state.currentIndex + 1).coerceAtMost(state.items.size)} / ${state.items.size}"
                                else "사진 분류"
                            },
                            onBack = if (screen == AppScreen.HOME) null else onNavigateHome,
                        )
                    }
                ) { innerPadding ->
                    Column(Modifier.fillMaxSize().padding(innerPadding)) {
                        if (state.error != null) {
                            Text(
                                text = state.error,
                                color = MaterialTheme.colorScheme.error,
                                style = MaterialTheme.typography.bodyMedium,
                                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                            )
                        }
                        when (screen) {
                            AppScreen.HOME -> HomeScreen(
                                state = state,
                                access = access,
                                onOpenAlbums = onOpenAlbums,
                                onReviewPermission = onReviewPermission,
                                onOpenSettings = onOpenSettings,
                                onChoosePhotos = onChoosePhotos,
                                onContinue = onContinue,
                                onGooglePhotosHelp = { showGooglePhotosHelp = true },
                                onCreateAlbum = onCreateAlbum,
                                onRemoveAlbum = onRemoveAlbum,
                            )
                            AppScreen.ALBUMS -> AlbumScreen(
                                state = state,
                                access = access,
                                onReviewPermission = onReviewPermission,
                                onOpenSettings = onOpenSettings,
                                onRegister = {
                                    onRegisterAlbum(it)
                                    onNavigateHome()
                                },
                                onCreateAlbum = {
                                    onCreateAlbum(it)
                                    onNavigateHome()
                                },
                            )
                            AppScreen.CLASSIFY -> when {
                                state.items.isEmpty() -> LoadingSelection(state.busy)
                                state.currentIndex >= state.items.size -> CompletionScreen(
                                    state = state,
                                    onChoosePhotos = onChoosePhotos,
                                    onPrevious = onPrevious,
                                    onResetSession = onResetSession,
                                    onGooglePhotosHelp = { showGooglePhotosHelp = true },
                                )
                                else -> ClassificationScreen(
                                    state = state,
                                    onSubmit = onSubmit,
                                    onPrevious = onPrevious,
                                    onClearError = onClearError,
                                )
                            }
                        }
                    }
                }
            }
            if (showGooglePhotosHelp) {
                GooglePhotosHelpDialog(
                    onDismiss = { showGooglePhotosHelp = false },
                    onOpenGooglePhotos = {
                        showGooglePhotosHelp = false
                        onOpenGooglePhotos()
                    },
                )
            }
        }
    }
}

@Composable
private fun Header(title: String, onBack: (() -> Unit)?) {
    Column {
        Row(
            modifier = Modifier.fillMaxWidth().statusBarsPadding().height(56.dp)
                .padding(horizontal = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (onBack != null) {
                TextButton(onClick = onBack) { Text("뒤로") }
            }
            Text(
                title,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(start = if (onBack == null) 8.dp else 4.dp),
            )
        }
        HorizontalDivider()
    }
}

@Composable
private fun PermissionGate(
    previouslyRequested: Boolean,
    onConfirm: () -> Unit,
    onLater: () -> Unit,
    onSettings: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxSize().systemBarsPadding().padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("사진 접근 권한", style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(16.dp))
        Text(
            "휴대폰에 저장된 앨범을 앱 안에서 보여주고, 분류한 사진을 해당 앨범에 복사하려면 사진 접근 권한이 필요합니다. 원본 사진은 수정하거나 삭제하지 않습니다.",
            style = MaterialTheme.typography.bodyLarge,
        )
        Spacer(Modifier.height(12.dp))
        Text(
            "확인을 누르면 Android 권한 선택창이 열립니다. 사진을 일부만 허용하면 앨범 목록도 제한될 수 있습니다.",
            style = MaterialTheme.typography.bodyMedium,
        )
        if (previouslyRequested) {
            Spacer(Modifier.height(12.dp))
            Text("권한을 허용하지 않았다면 다시 요청하거나 설정에서 변경할 수 있습니다.",
                color = MaterialTheme.colorScheme.error)
        }
        Spacer(Modifier.height(28.dp))
        Button(onClick = onConfirm, modifier = Modifier.fillMaxWidth()) {
            Text("확인하고 권한 요청")
        }
        OutlinedButton(onClick = onLater, modifier = Modifier.fillMaxWidth()) {
            Text("나중에")
        }
        TextButton(onClick = onSettings, modifier = Modifier.fillMaxWidth()) {
            Text("앱 설정에서 권한 변경")
        }
    }
}

@Composable
private fun HomeScreen(
    state: SorterUiState,
    access: PhotoAccess,
    onOpenAlbums: () -> Unit,
    onReviewPermission: () -> Unit,
    onOpenSettings: () -> Unit,
    onChoosePhotos: () -> Unit,
    onContinue: () -> Unit,
    onGooglePhotosHelp: () -> Unit,
    onCreateAlbum: (String) -> Unit,
    onRemoveAlbum: (String) -> Unit,
) {
    var showCreate by remember { mutableStateOf(false) }
    var confirmReplace by remember { mutableStateOf(false) }
    val hasUnfinishedSession = state.items.isNotEmpty() && state.currentIndex < state.items.size

    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        when (access) {
            PhotoAccess.DENIED -> InfoCard(
                "앨범을 보려면 사진 접근 권한이 필요합니다. 사진 선택기는 지금도 사용할 수 있습니다."
            )
            PhotoAccess.PARTIAL -> {
                InfoCard("선택한 사진에 해당하는 앨범만 보일 수 있습니다.")
                Row {
                    TextButton(onClick = onReviewPermission) { Text("사진 접근 범위 변경") }
                    TextButton(onClick = onOpenSettings) { Text("앱 설정") }
                }
            }
            PhotoAccess.FULL -> Unit
        }

        if (state.mappings.isEmpty()) {
            InfoCard("사진을 넣을 앨범을 추가해 주세요. 사진마다 앨범 버튼을 여러 개 선택할 수 있습니다.")
        } else {
            state.mappings.forEach { mapping ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Text(mapping.albumDisplayName,
                            style = MaterialTheme.typography.titleMedium)
                        Row {
                            TextButton(onClick = { onRemoveAlbum(mapping.id) }) { Text("등록 제거") }
                        }
                    }
                }
            }
        }
        Button(onClick = onOpenAlbums, modifier = Modifier.fillMaxWidth()) { Text("+ 앨범 추가") }
        if (access == PhotoAccess.DENIED && Build.VERSION.SDK_INT >= 29) {
            OutlinedButton(onClick = { showCreate = true }, modifier = Modifier.fillMaxWidth()) {
                Text("+ 새 앨범 만들기")
            }
        }
        if (hasUnfinishedSession) {
            OutlinedButton(onClick = onContinue, modifier = Modifier.fillMaxWidth()) {
                Text("이전 분류 이어서 (${state.currentIndex + 1} / ${state.items.size})")
            }
        }
        Button(
            onClick = {
                if (hasUnfinishedSession) confirmReplace = true else onChoosePhotos()
            },
            modifier = Modifier.fillMaxWidth(),
        ) { Text("사진 선택하기") }
        Text("사진 선택에는 전체 갤러리 접근 권한이 필요하지 않습니다.",
            style = MaterialTheme.typography.bodySmall)
        OutlinedButton(onClick = onGooglePhotosHelp, modifier = Modifier.fillMaxWidth()) {
            Text("Google 포토 정리 방법")
        }
    }

    if (confirmReplace) {
        AlertDialog(
            onDismissRequest = { confirmReplace = false },
            title = { Text("새 사진을 선택할까요?") },
            text = { Text("현재 분류 진행 상태가 새 사진 목록으로 바뀝니다.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmReplace = false
                    onChoosePhotos()
                }) { Text("새 사진 선택") }
            },
            dismissButton = {
                TextButton(onClick = { confirmReplace = false }) { Text("취소") }
            },
        )
    }
    if (showCreate) {
        AlbumNameDialog(
            onDismiss = { showCreate = false },
            onCreate = { name ->
                showCreate = false
                onCreateAlbum(name)
            },
        )
    }
}

@Composable
private fun AlbumScreen(
    state: SorterUiState,
    access: PhotoAccess,
    onReviewPermission: () -> Unit,
    onOpenSettings: () -> Unit,
    onRegister: (DeviceAlbum) -> Unit,
    onCreateAlbum: (String) -> Unit,
) {
    var showCreate by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize()) {
        if (access == PhotoAccess.PARTIAL) {
            InfoCard("사진 일부만 허용되어 앨범 목록이 제한됩니다.")
            Row(Modifier.padding(horizontal = 12.dp)) {
                TextButton(onClick = onReviewPermission) { Text("사진 접근 범위 변경") }
                TextButton(onClick = onOpenSettings) { Text("앱 설정") }
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("기기 앨범", style = MaterialTheme.typography.titleMedium)
            TextButton(onClick = { showCreate = true }) { Text("+ 새 앨범") }
        }
        when {
            state.loadingAlbums -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            state.albums.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("표시할 로컬 앨범이 없습니다. 새 앨범을 만들 수 있습니다.",
                    modifier = Modifier.padding(24.dp), textAlign = TextAlign.Center)
            }
            else -> LazyVerticalGrid(
                columns = GridCells.Adaptive(minSize = 140.dp),
                modifier = Modifier.fillMaxSize().padding(horizontal = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                items(state.albums, key = { it.id }) { album ->
                    val registered = state.mappings.any { it.id == album.id }
                    Card(
                        modifier = Modifier.fillMaxWidth().clickable(
                            enabled = album.writable && !registered,
                            onClick = { onRegister(album) }
                        ),
                    ) {
                        Column {
                            AsyncImage(
                                model = album.coverUri.takeIf(String::isNotBlank)?.let(Uri::parse),
                                contentDescription = "${album.displayName} 앨범 대표 사진",
                                modifier = Modifier.fillMaxWidth().aspectRatio(1f),
                                contentScale = ContentScale.Crop,
                            )
                            Column(Modifier.padding(10.dp)) {
                                Text(album.displayName, style = MaterialTheme.typography.titleSmall,
                                    maxLines = 2)
                                Text("${album.count}장", style = MaterialTheme.typography.bodySmall)
                                if (registered) Text("등록됨", style = MaterialTheme.typography.labelSmall)
                                else if (!album.writable) Text("저장할 수 없음",
                                    color = MaterialTheme.colorScheme.error,
                                    style = MaterialTheme.typography.labelSmall)
                            }
                        }
                    }
                }
            }
        }
    }
    if (showCreate) {
        AlbumNameDialog(
            onDismiss = { showCreate = false },
            onCreate = { name ->
                showCreate = false
                onCreateAlbum(name)
            },
        )
    }
}

@Composable
private fun AlbumNameDialog(onDismiss: () -> Unit, onCreate: (String) -> Unit) {
    var albumName by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("새 앨범") },
        text = {
            Column {
                Text("첫 사진을 복사하면 일반 갤러리에도 앨범이 나타납니다.")
                OutlinedTextField(
                    value = albumName,
                    onValueChange = { albumName = it },
                    label = { Text("앨범 이름") },
                    singleLine = true,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onCreate(albumName) }) { Text("등록") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("취소") } },
    )
}

@Composable
private fun ClassificationScreen(
    state: SorterUiState,
    onSubmit: (Set<String>) -> Unit,
    onPrevious: () -> Unit,
    onClearError: () -> Unit,
) {
    val item = state.items[state.currentIndex]
    var selectedTargets by rememberSaveable(state.currentIndex, item.sourceUri) {
        mutableStateOf(ArrayList(item.selectedTargets))
    }
    var imageFailed by remember(item.sourceUri) { mutableStateOf(false) }
    val availableTargets = state.mappings.map { it.targetKey() }.toSet()
    val missingTargets = selectedTargets.filterNot { it in availableTargets }
    val duplicateNames = state.mappings.groupingBy { it.albumDisplayName }.eachCount()
    Column(Modifier.fillMaxSize().padding(horizontal = 12.dp, vertical = 8.dp)) {
        Box(Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.Center) {
            AsyncImage(
                model = Uri.parse(item.sourceUri),
                contentDescription = "분류할 사진 ${state.currentIndex + 1}",
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Fit,
                onError = { imageFailed = true },
                onSuccess = { imageFailed = false },
            )
        }
        if (imageFailed) {
            Text("원본 사진을 표시할 수 없습니다. 뒤로 가서 사진을 다시 선택해 주세요.",
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyMedium)
        }
        if (item.errorMessage != null) {
            Text(item.errorMessage,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(vertical = 4.dp))
        }
        if (state.busy) {
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                Text("처리하는 중…")
            }
        }
        Text(
            "사진을 넣을 앨범 선택",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "여러 개 선택할 수 있습니다. 앨범을 누를 때는 선택만 하고, 다음을 누르면 복사합니다.",
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(bottom = 8.dp),
        )
        if (state.mappings.isEmpty()) {
            InfoCard("등록된 앨범이 없습니다. 상단 뒤로를 누른 다음 앨범을 추가해 주세요.")
        } else {
            FlowRow(
                modifier = Modifier.fillMaxWidth().heightIn(max = 220.dp)
                    .verticalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                state.mappings.forEach { mapping ->
                    val target = mapping.targetKey()
                    val isSelected = target in selectedTargets
                    Button(
                        onClick = {
                            selectedTargets = ArrayList(selectedTargets).apply {
                                if (isSelected) remove(target) else add(target)
                            }
                            onClearError()
                        },
                        enabled = !state.busy && !imageFailed,
                        modifier = Modifier.semantics { selected = isSelected },
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (isSelected) MaterialTheme.colorScheme.primary
                                else MaterialTheme.colorScheme.primaryContainer,
                            contentColor = if (isSelected) MaterialTheme.colorScheme.onPrimary
                                else MaterialTheme.colorScheme.onPrimaryContainer,
                        ),
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text((if (isSelected) "✓ " else "") + mapping.albumDisplayName)
                            if (duplicateNames.getValue(mapping.albumDisplayName) > 1) {
                                Text(albumLocationLabel(mapping),
                                    style = MaterialTheme.typography.labelSmall)
                            }
                        }
                    }
                }
            }
        }
        if (missingTargets.isNotEmpty()) {
            Text("이전에 선택한 앨범이 등록 목록에서 사라졌습니다.",
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = {
                selectedTargets = ArrayList(selectedTargets.filter { it in availableTargets })
                onClearError()
            }) { Text("없는 앨범 선택 해제") }
        }
        if (item.completedTargets.isNotEmpty()) {
            Text("이미 복사된 사진은 선택을 풀어도 복사본이 남습니다.",
                style = MaterialTheme.typography.bodySmall)
        }
        Text("${selectedTargets.size}개 앨범 선택 · 선택하지 않으면 이 사진을 건너뜁니다.",
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(vertical = 6.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (state.currentIndex > 0) {
                OutlinedButton(onClick = onPrevious, enabled = !state.busy,
                    modifier = Modifier.weight(1f)) { Text("이전 사진") }
            }
            Button(
                onClick = { onSubmit(selectedTargets.toSet()) },
                enabled = !state.busy && !imageFailed && missingTargets.isEmpty(),
                modifier = Modifier.weight(1f),
            ) { Text("다음") }
        }
    }
}

private fun albumLocationLabel(mapping: AlbumMapping): String {
    val storage = if (mapping.volumeName in setOf("external_primary", "primary", "external")) {
        "내장 저장소"
    } else {
        "외장 저장소"
    }
    val folders = mapping.relativePath.trim('/').split('/').filter(String::isNotBlank)
    val parent = folders.dropLast(1).lastOrNull()
    return if (parent.isNullOrBlank() || parent.equals("Pictures", ignoreCase = true)) {
        storage
    } else {
        "$parent · $storage"
    }
}

@Composable
private fun CompletionScreen(
    state: SorterUiState,
    onChoosePhotos: () -> Unit,
    onPrevious: () -> Unit,
    onResetSession: () -> Unit,
    onGooglePhotosHelp: () -> Unit,
) {
    val copied = state.items.count { it.status == PhotoStatus.COMPLETED }
    val copiedFiles = state.items.sumOf { it.newCopies.size }
    val skipped = state.items.count { it.status == PhotoStatus.SKIPPED }
    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("분류 완료", style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(16.dp))
        Text("전체 ${state.items.size}장 · 분류 ${copied}장 · 복사된 파일 ${copiedFiles}개 · 건너뜀 ${skipped}장")
        Spacer(Modifier.height(16.dp))
        InfoCard("이미 분류한 사진을 Google 포토의 '사진' 화면에서만 숨기려면 원본과 복사본을 모두 보관처리하세요. 기기 앨범의 파일은 남습니다.")
        OutlinedButton(onClick = onGooglePhotosHelp, modifier = Modifier.fillMaxWidth()) {
            Text("Google 포토 정리 방법")
        }
        Spacer(Modifier.height(12.dp))
        Button(onClick = onChoosePhotos, modifier = Modifier.fillMaxWidth()) {
            Text("새 사진 선택")
        }
        OutlinedButton(onClick = onPrevious, modifier = Modifier.fillMaxWidth()) {
            Text("이전 사진")
        }
        OutlinedButton(onClick = onResetSession, modifier = Modifier.fillMaxWidth()) {
            Text("앨범 화면으로")
        }
    }
}

@Composable
private fun GooglePhotosHelpDialog(
    onDismiss: () -> Unit,
    onOpenGooglePhotos: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("분류한 사진 숨기기") },
        text = {
            Column(
                modifier = Modifier.heightIn(max = 430.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(
                    "Google 포토에서 기기 복사본을 삭제하면 갤러리 앨범의 같은 파일도 삭제됩니다. 앨범에 남겨둘 사진은 삭제하지 마세요.",
                    color = MaterialTheme.colorScheme.error,
                    fontWeight = FontWeight.SemiBold,
                )
                Text("1. Google 포토 '사진'에서 처리한 사진을 열고 ⋮ → 정보에서 폴더를 확인합니다.")
                Text("2. 뒤로 돌아와 사진을 길게 눌러 선택합니다. 화면에서 모두 치우려면 원본과 분류 폴더의 복사본을 모두 고르세요.")
                Text("3. ⋮ → 보관처리를 누릅니다. 기기 폴더의 파일은 남고 '사진' 화면에서만 사라집니다.")
                Text("복사본만 고르면 원본은 계속 보입니다. 보관한 사진은 컬렉션 → 보관 파일에서 찾거나 보관 취소할 수 있습니다.")
                Text("Google 포토 보관 상태는 이 앱에서 대신 바꿀 수 없습니다. 아래 버튼으로 Google 포토를 열어 진행하세요.")
            }
        },
        confirmButton = {
            TextButton(onClick = onOpenGooglePhotos) { Text("Google 포토 열기") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("닫기") }
        },
    )
}

@Composable
private fun LoadingSelection(busy: Boolean) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        if (busy) CircularProgressIndicator()
        else Text("사진을 선택하면 분류를 시작합니다.")
    }
}

@Composable
private fun InfoCard(message: String) {
    Card(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp),
        shape = RoundedCornerShape(12.dp)) {
        Text(message, modifier = Modifier.padding(16.dp),
            style = MaterialTheme.typography.bodyMedium)
    }
}
