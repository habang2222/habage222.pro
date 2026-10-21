package com.example.photosorter

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ViewModelProvider
import com.example.photosorter.ui.AppScreen
import com.example.photosorter.ui.PhotoAccess
import com.example.photosorter.ui.PhotoSorterApp
import com.example.photosorter.viewmodel.PhotoSorterViewModel

class MainActivity : ComponentActivity() {
    private val sorter by lazy { ViewModelProvider(this)[PhotoSorterViewModel::class.java] }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContent {
            val state by sorter.state.collectAsState()
            var access by remember { mutableStateOf(photoAccess()) }
            var screen by rememberSaveable { mutableStateOf(AppScreen.HOME.name) }
            var showPermissionGate by rememberSaveable {
                mutableStateOf(access == PhotoAccess.DENIED)
            }
            var openAlbumsAfterPermission by rememberSaveable { mutableStateOf(false) }
            var openGalleryAfterPermission by rememberSaveable { mutableStateOf(false) }
            var permissionWasRequested by rememberSaveable { mutableStateOf(false) }

            val permissionLauncher = rememberLauncherForActivityResult(
                ActivityResultContracts.RequestMultiplePermissions()
            ) {
                access = photoAccess()
                showPermissionGate = access == PhotoAccess.DENIED
                if (access != PhotoAccess.DENIED) {
                    if (openAlbumsAfterPermission) {
                        screen = AppScreen.ALBUMS.name
                        openAlbumsAfterPermission = false
                    }
                    if (openGalleryAfterPermission) {
                        screen = AppScreen.GALLERY.name
                        openGalleryAfterPermission = false
                    }
                    if (screen == AppScreen.ALBUMS.name) sorter.refreshAlbums()
                    if (screen == AppScreen.GALLERY.name) sorter.refreshLocalGallery()
                }
            }

            // A grant can change in system Settings while this activity is paused.
            DisposableEffect(lifecycle, access, screen) {
                val observer = LifecycleEventObserver { _, event ->
                    if (event == Lifecycle.Event.ON_RESUME) {
                        val current = photoAccess()
                        access = current
                        if (current != PhotoAccess.DENIED && openAlbumsAfterPermission) {
                            screen = AppScreen.ALBUMS.name
                            openAlbumsAfterPermission = false
                            showPermissionGate = false
                        }
                        if (current != PhotoAccess.DENIED && openGalleryAfterPermission) {
                            screen = AppScreen.GALLERY.name
                            openGalleryAfterPermission = false
                            showPermissionGate = false
                        }
                        if (current == PhotoAccess.DENIED &&
                            (screen == AppScreen.ALBUMS.name || screen == AppScreen.GALLERY.name)
                        ) {
                            screen = AppScreen.HOME.name
                            sorter.clearLocalGallery()
                        } else if (current != PhotoAccess.DENIED &&
                            screen == AppScreen.ALBUMS.name
                        ) {
                            // The user may have changed the selected photo set without
                            // changing the PARTIAL permission state.
                            sorter.refreshAlbums()
                        } else if (current != PhotoAccess.DENIED &&
                            screen == AppScreen.GALLERY.name
                        ) {
                            sorter.refreshLocalGallery()
                        }
                    }
                }
                lifecycle.addObserver(observer)
                onDispose { lifecycle.removeObserver(observer) }
            }

            PhotoSorterApp(
                state = state,
                access = access,
                screen = AppScreen.valueOf(screen),
                showPermissionGate = showPermissionGate && access == PhotoAccess.DENIED,
                permissionWasRequested = permissionWasRequested,
                onConfirmPermission = {
                    permissionWasRequested = true
                    permissionLauncher.launch(requiredPermissions())
                },
                onReviewPermission = {
                    permissionWasRequested = true
                    permissionLauncher.launch(requiredPermissions())
                },
                onPermissionLater = {
                    showPermissionGate = false
                    openAlbumsAfterPermission = false
                    openGalleryAfterPermission = false
                },
                onOpenSettings = {
                    startActivity(Intent(
                        Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.parse("package:$packageName")
                    ))
                },
                onOpenSamsungGallery = {
                    val launchIntent = packageManager.getLaunchIntentForPackage(SAMSUNG_GALLERY_PACKAGE)
                    if (launchIntent == null) {
                        Toast.makeText(this, "삼성 갤러리 앱을 찾지 못했습니다.", Toast.LENGTH_LONG).show()
                    } else {
                        try {
                            startActivity(launchIntent)
                        } catch (_: ActivityNotFoundException) {
                            Toast.makeText(this, "삼성 갤러리를 열 수 없습니다.", Toast.LENGTH_LONG).show()
                        } catch (_: SecurityException) {
                            Toast.makeText(this, "삼성 갤러리를 열 수 없습니다.", Toast.LENGTH_LONG).show()
                        }
                    }
                },
                onNavigateHome = { screen = AppScreen.HOME.name },
                onOpenAlbums = {
                    if (access == PhotoAccess.DENIED) {
                        openAlbumsAfterPermission = true
                        showPermissionGate = true
                    } else {
                        screen = AppScreen.ALBUMS.name
                        sorter.refreshAlbums()
                    }
                },
                onChoosePhotos = {
                    if (access == PhotoAccess.DENIED) {
                        openGalleryAfterPermission = true
                        showPermissionGate = true
                    } else {
                        screen = AppScreen.GALLERY.name
                        sorter.refreshLocalGallery()
                    }
                },
                onOpenGalleryAlbum = { key -> sorter.openLocalGalleryAlbum(key) },
                onBackToGalleryAlbums = { sorter.backToLocalGalleryAlbums() },
                onToggleGalleryPhoto = { uri -> sorter.toggleLocalGalleryPhoto(uri) },
                onToggleGalleryProcessed = { sorter.toggleLocalGalleryProcessed() },
                onLoadMoreGalleryPhotos = { sorter.loadMoreLocalGalleryPhotos() },
                onConfirmGallerySelection = {
                    val selected = sorter.state.value.gallery.selectedUris.map(Uri::parse)
                    if (selected.isNotEmpty()) {
                        sorter.selectPhotos(selected)
                        screen = AppScreen.CLASSIFY.name
                    }
                },
                onContinue = { screen = AppScreen.CLASSIFY.name },
                onRegisterAlbum = { album -> sorter.addAlbum(album) },
                onCreateAlbum = { name -> sorter.createAlbum(name) },
                onRemoveAlbum = { id -> sorter.removeAlbum(id) },
                onSubmit = { targets -> sorter.submit(targets) },
                onPrevious = { sorter.previous() },
                onResetSession = {
                    sorter.resetSession()
                    screen = AppScreen.HOME.name
                },
                onClearError = { sorter.clearError() }
            )
        }
    }

    private fun hasPermission(permission: String): Boolean =
        ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED

    private fun photoAccess(): PhotoAccess = when {
        Build.VERSION.SDK_INT >= 34 && hasPermission(Manifest.permission.READ_MEDIA_IMAGES) ->
            PhotoAccess.FULL
        Build.VERSION.SDK_INT >= 34 &&
            hasPermission(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED) ->
            PhotoAccess.PARTIAL
        Build.VERSION.SDK_INT >= 33 && hasPermission(Manifest.permission.READ_MEDIA_IMAGES) ->
            PhotoAccess.FULL
        Build.VERSION.SDK_INT in 29..32 &&
            hasPermission(Manifest.permission.READ_EXTERNAL_STORAGE) ->
            PhotoAccess.FULL
        Build.VERSION.SDK_INT <= 28 &&
            hasPermission(Manifest.permission.READ_EXTERNAL_STORAGE) &&
            hasPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) ->
            PhotoAccess.FULL
        else -> PhotoAccess.DENIED
    }

    private fun requiredPermissions(): Array<String> = when {
        Build.VERSION.SDK_INT >= 34 -> arrayOf(
            Manifest.permission.READ_MEDIA_IMAGES,
            Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED
        )
        Build.VERSION.SDK_INT >= 33 -> arrayOf(Manifest.permission.READ_MEDIA_IMAGES)
        Build.VERSION.SDK_INT >= 29 -> arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE)
        else -> arrayOf(
            Manifest.permission.READ_EXTERNAL_STORAGE,
            Manifest.permission.WRITE_EXTERNAL_STORAGE
        )
    }

    companion object {
        private const val SAMSUNG_GALLERY_PACKAGE = "com.sec.android.gallery3d"
    }
}
