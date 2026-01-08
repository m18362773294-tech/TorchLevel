<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
android:id="@+id/root"
android:layout_width="match_parent"
android:layout_height="match_parent"
android:gravity="center_horizontal"
android:orientation="vertical"
android:padding="24dp">

<TextView
android:id="@+id/tvStatus"
android:layout_width="match_parent"
android:layout_height="wrap_content"
android:text="状态：初始化中…"
android:textSize="16sp"
android:paddingBottom="16dp" />

<Button
android:id="@+id/btnToggle"
android:layout_width="match_parent"
android:layout_height="72dp"
android:text="开"
android:textSize="26sp" />

<TextView
android:id="@+id/tvLevel"
android:layout_width="match_parent"
android:layout_height="wrap_content"
android:text="档位：- / -"
android:textSize="18sp"
android:paddingTop="18dp"
android:paddingBottom="6dp" />

<SeekBar
android:id="@+id/seekLevel"
android:layout_width="match_parent"
android:layout_height="wrap_content"
android:max="0"
android:enabled="false" />

<TextView
android:id="@+id/tvHint"
android:layout_width="match_parent"
android:layout_height="wrap_content"
android:text="提示：若本机不支持档位调光，档位条会自动禁用。"
android:textSize="13sp"
android:alpha="0.75"
android:paddingTop="14dp" />

</LinearLayout>
