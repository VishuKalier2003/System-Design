package Singleton;

import java.io.FileWriter;
import java.io.PrintWriter;

// Imp - This class behaves as a @Bean or @Configuration class (having only one instance across entire application)
public class Singleton {
    // volatile ensures any thread reading the variable sees the most up-to-date value (Read repair)
    private static volatile Singleton activeInstance;       // variable to store the active singleton instance
    public int value;
    public static final String LOG_FILE = "Singleton/application.log";
    private PrintWriter writer;     // Print writer created

    // private constructor to prevent instantiation
    private Singleton(int value) {
        try {
            FileWriter fileWriter = new FileWriter(LOG_FILE, true);     // Opening a file in append mode
            writer = new PrintWriter(fileWriter, true);     // Allows auto-flush in printing
            this.value = value;
        } catch (Exception e) {e.printStackTrace();}
    }

    public static Singleton getInstance(int value) {
        if(activeInstance == null) {        // When current instance is not yet created
            synchronized (Singleton.class) {        // Locks the code block, preventing multiple threads to enter and create many instances
                // Imp - When the instance is null, create the first and only instance (critical section)
                if(activeInstance == null)  activeInstance = new Singleton(value);
            }
        }
        return activeInstance;      // Return the singleton instance
    }

    public void log(String log) {writer.println(log); System.out.println("Log : "+log); return;}

    public int getHashCode() {       // Generate and provide the hash code (when same instances the hash code are same)
        return activeInstance != null ? activeInstance.hashCode() : -1;
    }

    public int value() {return value;}

    public void close() {writer.close();}       // Close the writer and release the memory
}
