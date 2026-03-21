package com.sondehound.ble

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.bluetooth.*
import android.bluetooth.le.*
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.os.ParcelUuid
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import com.google.gson.Gson
import com.sondehound.data.AutoRxMessage
import com.sondehound.data.ReceiverMode
import com.sondehound.data.SondeRepository
import java.util.*

/**
 * Foreground service that manages BLE connection to the Pi Zero W.
 *
 * The Pi advertises a custom GATT service. We subscribe to a characteristic
 * that streams auto_rx JSON telemetry messages, one per notification.
 *
 * For messages longer than the BLE MTU, the Pi fragments them and we
 * reassemble using a simple newline delimiter.
 */
class BleService : Service() {

    companion object {
        private const val TAG = "BleService"
        private const val NOTIFICATION_ID = 1
        private const val CHANNEL_ID = "sondehound_ble"

        // Custom UUIDs for SondeHound BLE protocol
        val SERVICE_UUID: UUID = UUID.fromString("1c98734f-0510-4fa8-b9c9-b9cea7a631b0")
        val TELEMETRY_CHAR_UUID: UUID = UUID.fromString("f798a958-831b-46ba-bb3a-11a063c50ebc")
        val COMMAND_CHAR_UUID: UUID = UUID.fromString("b12af15d-0713-4783-bd68-73b07d4b689b")
        val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
    }

    private val binder = LocalBinder()
    private val gson = Gson()
    private var bluetoothGatt: BluetoothGatt? = null
    private var scanning = false
    private var isConnected = false

    private val reconnectHandler = Handler(Looper.getMainLooper())
    private val reconnectDelay = 3000L // ms

    // Keepalive: probe the Pi with a GATT read every 4s, reconnect if
    // no response (read or notify) within 10s
    private val keepaliveHandler = Handler(Looper.getMainLooper())
    private val keepaliveProbeInterval = 4_000L // ms
    private val keepaliveTimeout = 10_000L // ms
    @Volatile private var lastBleResponse = 0L
    private val keepaliveRunnable = object : Runnable {
        override fun run() {
            if (isConnected) {
                // Check if we've heard anything recently
                val elapsed = System.currentTimeMillis() - lastBleResponse
                if (lastBleResponse > 0 && elapsed > keepaliveTimeout) {
                    Log.w(TAG, "Keepalive: no BLE response for ${elapsed}ms, forcing reconnect")
                    forceReconnect()
                    return
                }
                // Send a GATT read as a ping
                try {
                    val char = bluetoothGatt?.getService(SERVICE_UUID)
                        ?.getCharacteristic(TELEMETRY_CHAR_UUID)
                    if (char != null) {
                        bluetoothGatt?.readCharacteristic(char)
                    }
                } catch (e: SecurityException) {
                    Log.e(TAG, "SecurityException in keepalive read", e)
                }
            }
            keepaliveHandler.postDelayed(this, keepaliveProbeInterval)
        }
    }

    // Synchronized buffer for reassembling fragmented BLE messages
    private val bufferLock = Object()
    private val messageBuffer = StringBuilder()

    inner class LocalBinder : Binder() {
        fun getService(): BleService = this@BleService
    }

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification("Idle"))
    }

    override fun onDestroy() {
        reconnectHandler.removeCallbacksAndMessages(null)
        keepaliveHandler.removeCallbacksAndMessages(null)
        stopScanning()
        disconnectGatt()
        super.onDestroy()
    }

    private fun forceReconnect() {
        Log.i(TAG, "Force reconnecting...")
        isConnected = false
        lastBleResponse = 0
        keepaliveHandler.removeCallbacks(keepaliveRunnable)
        disconnectGatt()
        synchronized(bufferLock) { messageBuffer.clear() }
        SondeRepository.setConnected(false)
        SondeRepository.updateConnectionStatus("Reconnecting...")
        updateNotification("Reconnecting...")
        reconnectHandler.postDelayed({ startScanning() }, reconnectDelay)
    }

    // -- Public API --

    fun startScanning() {
        if (scanning) return
        if (!hasBluetoothPermissions()) {
            Log.w(TAG, "Missing Bluetooth permissions")
            SondeRepository.updateConnectionStatus("Missing permissions")
            return
        }

        val bluetoothManager = getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
        val scanner = bluetoothManager.adapter?.bluetoothLeScanner
        if (scanner == null) {
            SondeRepository.updateConnectionStatus("Bluetooth not available")
            return
        }

        val filters = listOf(
            ScanFilter.Builder()
                .setServiceUuid(ParcelUuid(SERVICE_UUID))
                .build()
        )
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build()

        try {
            scanner.startScan(filters, settings, scanCallback)
            scanning = true
            SondeRepository.updateConnectionStatus("Searching for SondeHound...")
            updateNotification("Searching for SondeHound...")
        } catch (e: SecurityException) {
            Log.e(TAG, "SecurityException starting scan", e)
            SondeRepository.updateConnectionStatus("Permission denied")
        }
    }

    fun stopScanning() {
        if (!scanning) return
        val bluetoothManager = getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
        val scanner = bluetoothManager.adapter?.bluetoothLeScanner ?: return
        try {
            scanner.stopScan(scanCallback)
        } catch (e: SecurityException) {
            Log.e(TAG, "SecurityException stopping scan", e)
        }
        scanning = false
    }

    fun disconnect() {
        disconnectGatt()
        SondeRepository.setConnected(false)
        SondeRepository.updateConnectionStatus("Disconnected")
        updateNotification("Disconnected")
    }

    fun sendModeCommand(mode: ReceiverMode, frequency: Double? = null) {
        val gatt = bluetoothGatt ?: return
        val commandChar = gatt.getService(SERVICE_UUID)
            ?.getCharacteristic(COMMAND_CHAR_UUID) ?: return

        val command = when (mode) {
            ReceiverMode.AUTO -> """{"mode":"auto"}"""
            ReceiverMode.FREQUENCY -> """{"mode":"frequency","freq":${frequency ?: 403.0}}"""
        }

        val bytes = command.toByteArray(Charsets.UTF_8)
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                gatt.writeCharacteristic(
                    commandChar, bytes, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
                )
            } else {
                @Suppress("DEPRECATION")
                commandChar.value = bytes
                @Suppress("DEPRECATION")
                gatt.writeCharacteristic(commandChar)
            }
        } catch (e: SecurityException) {
            Log.e(TAG, "SecurityException writing command", e)
        }
    }

    // -- BLE Scanning --

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            stopScanning()
            SondeRepository.updateConnectionStatus("Connecting...")
            updateNotification("Connecting...")
            connectToDevice(result.device)
        }

        override fun onScanFailed(errorCode: Int) {
            Log.e(TAG, "Scan failed: $errorCode")
            scanning = false
            SondeRepository.updateConnectionStatus("Scan failed ($errorCode)")
        }
    }

    // -- BLE Connection --

    private fun connectToDevice(device: BluetoothDevice) {
        try {
            bluetoothGatt = device.connectGatt(this, false, gattCallback)
        } catch (e: SecurityException) {
            Log.e(TAG, "SecurityException connecting", e)
            SondeRepository.updateConnectionStatus("Permission denied")
        }
    }

    private fun disconnectGatt() {
        try {
            bluetoothGatt?.disconnect()
            bluetoothGatt?.close()
        } catch (e: SecurityException) {
            Log.e(TAG, "SecurityException disconnecting", e)
        }
        bluetoothGatt = null
    }

    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> {
                    Log.i(TAG, "Connected to GATT server")
                    SondeRepository.updateConnectionStatus("Discovering services...")
                    try {
                        gatt.discoverServices()
                    } catch (e: SecurityException) {
                        Log.e(TAG, "SecurityException discovering services", e)
                    }
                }
                BluetoothProfile.STATE_DISCONNECTED -> {
                    Log.i(TAG, "Disconnected from GATT server")
                    isConnected = false
                    lastBleResponse = 0
                    keepaliveHandler.removeCallbacks(keepaliveRunnable)
                    SondeRepository.setConnected(false)
                    SondeRepository.updateConnectionStatus("Reconnecting...")
                    updateNotification("Reconnecting...")
                    try {
                        gatt.close()
                    } catch (_: SecurityException) {}
                    bluetoothGatt = null
                    reconnectHandler.postDelayed({ startScanning() }, reconnectDelay)
                }
            }
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                Log.e(TAG, "Service discovery failed: $status")
                return
            }

            val telemetryChar = gatt.getService(SERVICE_UUID)
                ?.getCharacteristic(TELEMETRY_CHAR_UUID)

            if (telemetryChar == null) {
                Log.e(TAG, "Telemetry characteristic not found")
                SondeRepository.updateConnectionStatus("Incompatible device")
                return
            }

            // Subscribe to telemetry notifications
            try {
                gatt.setCharacteristicNotification(telemetryChar, true)
                val descriptor = telemetryChar.getDescriptor(CCCD_UUID)
                if (descriptor == null) {
                    Log.e(TAG, "CCCD descriptor not found")
                    return
                }
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    gatt.writeDescriptor(
                        descriptor, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                    )
                } else {
                    @Suppress("DEPRECATION")
                    descriptor.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                    @Suppress("DEPRECATION")
                    gatt.writeDescriptor(descriptor)
                }
            } catch (e: SecurityException) {
                Log.e(TAG, "SecurityException subscribing", e)
            }

            isConnected = true
            lastBleResponse = System.currentTimeMillis()
            keepaliveHandler.postDelayed(keepaliveRunnable, keepaliveProbeInterval)
            SondeRepository.setConnected(true)
            SondeRepository.updateConnectionStatus("Connected to SondeHound, scanning for sondes")
            updateNotification("Connected - receiving data")
        }

        // Record successful GATT reads (keepalive pings)
        override fun onCharacteristicRead(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray,
            status: Int
        ) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                lastBleResponse = System.currentTimeMillis()
            }
        }

        @Deprecated("Deprecated in API 33")
        override fun onCharacteristicRead(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            status: Int
        ) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                lastBleResponse = System.currentTimeMillis()
            }
        }

        // API 33+ callback
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray
        ) {
            if (characteristic.uuid == TELEMETRY_CHAR_UUID) {
                handleTelemetryChunk(value.toString(Charsets.UTF_8))
            }
        }

        // Pre-API 33 callback
        @Deprecated("Deprecated in API 33")
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic
        ) {
            if (characteristic.uuid == TELEMETRY_CHAR_UUID) {
                @Suppress("DEPRECATION")
                val chunk = characteristic.value?.toString(Charsets.UTF_8) ?: return
                handleTelemetryChunk(chunk)
            }
        }
    }

    // -- Message reassembly and parsing --

    private fun handleTelemetryChunk(chunk: String) {
        lastBleResponse = System.currentTimeMillis()
        synchronized(bufferLock) {
            messageBuffer.append(chunk)
            val content = messageBuffer.toString()
            val newlineIdx = content.indexOf('\n')
            if (newlineIdx >= 0) {
                val jsonStr = content.substring(0, newlineIdx)
                messageBuffer.clear()
                messageBuffer.append(content.substring(newlineIdx + 1))

                try {
                    val msg = gson.fromJson(jsonStr, AutoRxMessage::class.java)
                    SondeRepository.handleAutoRxMessage(msg)
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to parse telemetry JSON: $jsonStr", e)
                }
            }
        }
    }

    // -- Permissions --

    private fun hasBluetoothPermissions(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            ActivityCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_SCAN) ==
                PackageManager.PERMISSION_GRANTED &&
            ActivityCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_CONNECT) ==
                PackageManager.PERMISSION_GRANTED
        } else {
            ActivityCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED
        }
    }

    // -- Notifications --

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "SondeHound BLE",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "BLE connection status"
        }
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(channel)
    }

    private fun buildNotification(status: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("SondeHound")
            .setContentText(status)
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(status: String) {
        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(NOTIFICATION_ID, buildNotification(status))
    }
}
