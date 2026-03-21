package com.sondehound

import android.app.Application
import androidx.preference.PreferenceManager
import org.osmdroid.config.Configuration

class SondeHoundApp : Application() {
    override fun onCreate() {
        super.onCreate()
        // Configure osmdroid - must load preferences first
        val ctx = applicationContext
        Configuration.getInstance().load(ctx, PreferenceManager.getDefaultSharedPreferences(ctx))
        Configuration.getInstance().userAgentValue = packageName
        Configuration.getInstance().osmdroidTileCache = cacheDir.resolve("osmdroid")
    }
}
